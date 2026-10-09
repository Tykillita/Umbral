"""Comprueba las cuatro exportaciones audiovisuales y sus fuentes de captura."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seconds(value):
    hours, minutes, rest = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def main():
    results = []
    story = json.loads((ROOT / "storyboard.json").read_text(encoding="utf-8"))
    for lang in ["es", "en"]:
        captions = (ROOT / f"umbral-{lang}.vtt").read_text(encoding="utf-8")
        assert captions.startswith("WEBVTT\n")
        assert not any(marker in captions for marker in ["\u00c3\u0192", "\u00c2\u00b7", "\ufffd"]), "Texto con codificación corrupta"
        times = re.findall(r"(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3})", captions)
        assert len(times) == sum(len(scene[lang]["captions"]) for scene in story["scenes"])
        actual_text = " ".join(line for line in captions.splitlines() if line and line != "WEBVTT" and " --> " not in line)
        expected_text = " ".join(scene[lang]["narration"] for scene in story["scenes"])
        assert actual_text == expected_text, "Los subtítulos deben conservar todo el guion hablado"
        previous = 0
        for start, end in times:
            start, end = seconds(start), seconds(end)
            assert previous <= start < end <= 77
            previous = end
        for kind, size in [("tour", (1920, 1080)), ("reel", (1080, 1920))]:
            path = ROOT / f"umbral-{kind}-{lang}.mp4"
            info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)]))
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
            assert (video["width"], video["height"]) == size
            assert video["codec_name"] == "h264" and video["pix_fmt"] == "yuv420p"
            assert video["avg_frame_rate"] == "30/1" and int(video["nb_read_frames"]) == 2310
            assert abs(float(video["duration"]) - 77) < .001
            assert audio["codec_name"] == "aac" and audio["channels"] == 2
            assert abs(float(info["format"]["duration"]) - 77) < .06
            pcm = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-ar", "48000", "-ac", "2", "-"])
            samples = np.frombuffer(pcm, dtype="<f4")
            peak = float(np.max(np.abs(samples)))
            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
            assert .02 < rms < .4 and peak < 1, "Audio vacío o saturado"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"], check=True)
            results.append({"file": path.name, "sha256": sha(path), "bytes": path.stat().st_size, "resolution": list(size), "fps": 30, "frames": 2310, "durationSeconds": 77, "audioPeakDbfs": round(20 * np.log10(peak), 3), "audioRmsDbfs": round(20 * np.log10(rms), 3), "captionCues": len(times)})
    captures = []
    for orientation in ["landscape", "portrait"]:
        path = ROOT / "captures" / f"{orientation}.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        assert source["offline"] and not source["containsFixtures"] and source["externalRequests"] == 0
        assert source["dataMode"] == "provisional"
        total_clicks = 0
        for scene in source["scenes"]:
            assert sha(ROOT / "captures" / scene["file"]) == scene["sha256"]
            for click in scene["clicks"]:
                assert 0 <= click["time"] < scene["duration"]
                assert 0 <= click["x"] <= source["viewport"]["width"] and 0 <= click["y"] <= source["viewport"]["height"]
            total_clicks += len(scene["clicks"])
        assert total_clicks >= 8
        captures.append({"orientation": orientation, "snapshotId": source["snapshotId"], "applicationCommit": source["applicationCommit"], "clicks": total_clicks, "containsFixtures": False, "externalRequests": 0})
    report = {"verifiedAtUtc": datetime.now(timezone.utc).isoformat(), "command": "python docs/video/verify.py", "passed": True, "exports": results, "captures": captures}
    (ROOT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK: 4 videos; 77 s; 30 fps; 2310 fotogramas; H.264/AAC; subtítulos, fuentes, clics y audio verificados.")


if __name__ == "__main__":
    main()
