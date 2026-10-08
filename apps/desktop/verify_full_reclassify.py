"""Reclasifica TODO el CURRENT real mediante el exe congelado y registra recursos."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import threading
import time
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent
ROOT = DESKTOP.parents[1]


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    executable = DESKTOP / "dist/umbral-sidecar/umbral-sidecar.exe"
    previous = ROOT / "data/snapshots" / (ROOT / "data/snapshots/CURRENT").read_text().strip()
    original_manifest_sha = digest(previous / "manifest.json")
    qa = DESKTOP / ".qa"
    qa.mkdir(exist_ok=True)
    output_dir = qa / "full-data"
    command = [str(executable), "--pipeline", "--data-dir", str(output_dir), "reclassify",
               "--previous", str(previous), "--no-set-current", "--json-progress"]
    env = dict(os.environ, UMBRAL_LAYA_MODEL_DIR=str(DESKTOP / "staging/laya"), HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", USE_TF="0", TOKENIZERS_PARALLELISM="false")
    started = datetime.now(UTC).isoformat()
    start = time.perf_counter()
    observed_peak = [0]
    with (qa / "full-reclassify.log").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8",
                                   env=env, creationflags=subprocess.CREATE_NO_WINDOW)

        def monitor():
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, process.pid)
            if not handle:
                return
            try:
                while process.poll() is None:
                    counters = MemoryCounters()
                    counters.cb = ctypes.sizeof(counters)
                    if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                        observed_peak[0] = max(observed_peak[0], counters.PeakWorkingSetSize)
                    time.sleep(.25)
            finally:
                kernel.CloseHandle(handle)

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        progress, result = [], None
        for line in process.stdout:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if "stage" in item:
                if item["completed"] % 100 == 0 or item["stage"] != "classification":
                    progress.append({**item, "elapsedSeconds": round(time.perf_counter() - start, 2)})
                    print(json.dumps(progress[-1]), flush=True)
            if "path" in item:
                result = item
        exit_code = process.wait()
        thread.join(timeout=1)
    duration = round(time.perf_counter() - start, 2)
    receipt = {"command": subprocess.list2cmdline(command), "startedAt": started,
               "finishedAt": datetime.now(UTC).isoformat(), "exitCode": exit_code,
               "durationSeconds": duration, "peakWorkingSetBytes": observed_peak[0], "progress": progress,
               "executableSha256": digest(executable), "originalSnapshotId": previous.name,
               "originalManifestSha256": original_manifest_sha, "result": "failed"}
    if exit_code == 0 and result is not None:
        candidate = Path(result["path"])
        manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
        receipt.update(candidateSnapshotId=candidate.name, candidateManifestSha256=digest(candidate / "manifest.json"),
                       count=manifest["counts"]["articlesValid"], classifier=manifest["classifier"], result="passed")
        assert receipt["count"] == json.loads((previous / "manifest.json").read_text(encoding="utf-8"))["counts"]["articlesValid"]
        verify = subprocess.run([str(executable), "--pipeline", "verify", str(candidate)], capture_output=True, text=True)
        receipt["verifyExitCode"] = verify.returncode
        assert verify.returncode == 0
        assert digest(previous / "manifest.json") == original_manifest_sha
        receipt["sourceSnapshotUnchanged"] = True
        assert not (output_dir / "snapshots/CURRENT").exists(), "El candidato no debe activarse por sí solo."
    (qa / "full-reclassify.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
