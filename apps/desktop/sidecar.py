"""Motor incluido: API local, tareas de datos en otro proceso y cierre conjunto.

La credencial efímera se lee de stdin. No se guarda ni se registra. El padre
Electron únicamente recibe el puerto por stdout; los datos se guardan aparte.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import traceback
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse


def backup_database(data_dir: Path, app_version: str) -> None:
    """SQLite online-backup antes de migrar una versión, incluidos WAL pendientes."""
    config_path = data_dir / "config.json"
    previous = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    database = data_dir / "umbral.sqlite"
    if database.exists() and previous.get("appVersion") != app_version:
        backups = data_dir / "backups"
        backups.mkdir(exist_ok=True)
        backup = backups / f"umbral-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.sqlite"
        with sqlite3.connect(database) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        with sqlite3.connect(backup) as verified:
            if verified.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("No se pudo verificar el respaldo antes de actualizar.")
    # Preserve future/user preferences across manual application upgrades.
    previous.update(appVersion=app_version, dataSchemaVersion=1)
    candidate = config_path.with_suffix(".tmp")
    candidate.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    candidate.replace(config_path)


def seed_data(resources: Path, data_dir: Path) -> Path:
    from umbral_pipeline.refresh import load_verified
    from umbral_pipeline.snapshot import activate_snapshot

    root = data_dir / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    current = root / "CURRENT"
    if current.exists():
        sid = current.read_text().strip()
        if re.fullmatch(r"\d{8}-[a-f0-9]{8}", sid):
            path = root / sid
            try:
                load_verified(path)
                return path
            except (OSError, ValueError, KeyError):
                pass
        # Recover from an interrupted/corrupt cut without touching SQLite or cases.
        available = []
        for path in root.iterdir():
            if path.is_dir() and re.fullmatch(r"\d{8}-[a-f0-9]{8}", path.name):
                try:
                    available.append((load_verified(path)["manifest"]["cutoffUtc"], path.name))
                except (OSError, ValueError, KeyError):
                    pass
        if available:
            path = root / max(available)[1]
            activate_snapshot(path)
            return path
    seed_root = resources / "snapshots"
    seed = seed_root / (seed_root / "CURRENT").read_text().strip()
    load_verified(seed)
    destination = root / seed.name
    if destination.exists():
        try:
            load_verified(destination)
        except (OSError, ValueError, KeyError):
            destination.rename(root / (".corrupt-" + destination.name + f"-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}"))
    if not destination.exists():
        shutil.copytree(seed, destination)
    load_verified(destination)
    activate_snapshot(destination)
    return destination


def discover_public_api(services, config_url: str) -> bool:
    """Lee sólo la configuración pública de Hosting; los fallos dejan plantillas."""
    if services.settings.public_api_url:
        return True
    if config_url != "https://site-umbral.web.app/public-config.json":
        return False
    import httpx

    try:
        with httpx.Client(timeout=8, follow_redirects=False) as client:
            response = client.get(config_url)
            response.raise_for_status()
            if len(response.content) > 4096:
                return False
            document = response.json()
        url = document.get("apiUrl")
        if document.get("schemaVersion") != 1 or not isinstance(url, str):
            return False
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".onrender.com")
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in {None, 443}):
            return False
        services.settings = replace(services.settings, public_api_url=url.rstrip("/"))
        return True
    except Exception:
        return False


class DesktopJobs:
    def __init__(self, app, resources: Path, data_dir: Path, feed_url: str):
        self.app, self.resources, self.data_dir, self.feed_url = app, resources, data_dir, feed_url
        self.lock = threading.Lock()
        self.worker: subprocess.Popen | None = None
        self.stopping = False
        self.status = {"snapshotId": (data_dir / "snapshots" / "CURRENT").read_text().strip(),
                       "busy": False, "operation": None, "message": None, "stage": "idle",
                       "completed": 0, "total": 0, "error": None, "available": True}

    def get_status(self):
        with self.lock:
            self.status["snapshotId"] = self.app.state.services.corpus.snapshot_id
            return dict(self.status)

    def start(self, operation: str):
        with self.lock:
            if self.status["busy"]:
                return None
            self.status.update(busy=True, operation=operation, stage="preparing", completed=0, total=0,
                               message="Preparando Laya local…" if operation == "reclassify" else "Buscando el corte más reciente…",
                               error=None)
        thread = threading.Thread(target=self._run, args=(operation,), daemon=True)
        thread.start()
        return self.get_status()

    def _progress(self, stage, completed=0, total=0):
        messages = {"classification": "Clasificando titulares con Laya en este equipo…",
                    "clustering": "Agrupando noticias y verificando referencias…",
                    "complete": "Datos listos.", "downloading": "Descargando datos verificados…"}
        with self.lock:
            self.status.update(stage=stage, completed=completed, total=total,
                               message=messages.get(stage, "Preparando datos…"))

    def _run(self, operation):
        try:
            completion = "Corte verificado y activado. Tus casos conservan sus citas originales."
            if operation == "reclassify":
                path = self._reclassify()
            else:
                path, changed = self._update()
                if not changed:
                    completion = ("Sin conexión: conservamos el último corte válido."
                                  if self.app.state.services.settings.offline else "El corte disponible ya está actualizado.")
            if self.stopping:
                return
            # Services validates and constructs the new corpus before replacing it.
            self.app.state.services.activate_snapshot(path)
            from umbral_pipeline.snapshot import activate_snapshot

            activate_snapshot(path)
            from umbral_api.auth import LOCAL_USER
            from umbral_pipeline.refresh import retain_snapshots

            referenced = {record.snapshot_id for record in self.app.state.services.repo.list_cases(LOCAL_USER)}
            retain_snapshots(self.data_dir / "snapshots", keep=7, referenced=referenced)
            with self.lock:
                self.status.update(snapshotId=path.name, busy=False, operation=None, stage="complete",
                                   message=completion)
        except Exception as exc:
            if os.environ.get("UMBRAL_DESKTOP_SMOKE") == "1":
                diagnostics = self.data_dir / "diagnostics"
                diagnostics.mkdir(exist_ok=True)
                (diagnostics / f"{operation}-exception.log").write_text(
                    "".join(traceback.format_exception(exc)), encoding="utf-8")
            with self.lock:
                self.status.update(busy=False, operation=None, stage="failed",
                                   error="No se pudo completar la tarea. Se conservan los datos anteriores.",
                                   message="El último corte válido sigue disponible.")
        finally:
            self.worker = None

    def _reclassify(self):
        previous = self.data_dir / "snapshots" / self.get_status()["snapshotId"]
        command = [sys.executable, "--pipeline"] if getattr(sys, "frozen", False) else [sys.executable,
                                                                                      str(Path(__file__).resolve()), "--pipeline"]
        command += ["--data-dir", str(self.data_dir), "reclassify", "--previous", str(previous),
                    "--no-set-current", "--json-progress"]
        env = dict(os.environ, UMBRAL_LAYA_MODEL_DIR=str(self.resources / "laya"),
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
        error_output = subprocess.DEVNULL
        error_file = None
        if os.environ.get("UMBRAL_DESKTOP_SMOKE") == "1":
            diagnostics = self.data_dir / "diagnostics"
            diagnostics.mkdir(exist_ok=True)
            error_file = (diagnostics / "reclassify-worker.log").open("w", encoding="utf-8")
            error_output = error_file
        self.worker = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error_output,
                                       text=True, encoding="utf-8", env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        path = None
        for line in self.worker.stdout:
            if self.stopping:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "stage" in message:
                self._progress(message["stage"], message.get("completed", 0), message.get("total", 0))
            if "path" in message:
                path = Path(message["path"])
        code = self.worker.wait()
        if error_file:
            error_file.close()
        if code != 0 or path is None:
            raise RuntimeError(f"Laya no pudo producir un corte válido (salida {code}; candidato recibido: {path is not None}).")
        if path.resolve().parent != (self.data_dir / "snapshots").resolve():
            raise RuntimeError("La tarea devolvió una ruta no permitida.")
        return path

    def _update(self):
        self._progress("downloading")
        feed = self.app.state.services.snapshot_feed
        changed = feed.refresh()
        if feed.last_error:
            raise RuntimeError("No se pudo actualizar el corte.")
        return self.app.state.services.corpus.path, changed

    def stop(self):
        self.stopping = True
        if self.worker is not None and self.worker.poll() is None:
            self.worker.kill()
            self.worker.wait(timeout=10)


def watch_parent(parent_pid: int, jobs: DesktopJobs, server):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, parent_pid)
        if handle:
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            kernel.CloseHandle(handle)
        jobs.stop()
        server.should_exit = True


def serve(config):
    import uvicorn
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from umbral_api.app import create_app
    from umbral_api.config import Settings

    token = config["token"]
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("Credencial local inválida.")
    resources = Path(config["resources"]).resolve()
    from umbral_pipeline.util import sha256_file

    bundle = json.loads((resources / "bundle-manifest.json").read_text(encoding="utf-8"))
    if sha256_file(resources / "laya/model.safetensors") != bundle["modelWeightsSha256"]:
        raise RuntimeError("Los pesos incluidos de Laya no superan la verificación SHA-256.")
    data_dir = Path(config["dataDir"]).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    seed = seed_data(resources, data_dir)
    backup_database(data_dir, config["version"])
    settings = Settings(snapshot_dir=seed, snapshots_root=data_dir / "snapshots", allow_fixture=False,
                        strict_integrity=True, local_mode=True, auth_mode="local", persistence="sqlite",
                        offline=bool(config.get("offline", False)),
                        sqlite_path=data_dir / "umbral.sqlite", web_dist=resources / "web", cors_origins=())
    if hasattr(settings, "desktop_token"):
        settings = replace(settings, desktop_token=token)
    if hasattr(settings, "public_api_url"):
        settings = replace(settings, public_api_url=config.get("publicApiUrl") or None)
    app = create_app(settings)
    # The first offline launch must be immediate. Refresh only after serving the UI.
    app.state.services.settings = replace(app.state.services.settings, snapshot_feed_url=config["feedUrl"])
    # Reattach the static mount last so desktop controls cannot be swallowed by it.
    app.router.routes = [r for r in app.router.routes if getattr(r, "name", None) != "web"]
    jobs = DesktopJobs(app, resources, data_dir, config["feedUrl"])
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen(128)
    expected_host = f"127.0.0.1:{port}"

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        if request.headers.get("host") != expected_host:
            return JSONResponse({"detail": "Origen local no autorizado."}, status_code=403)
        if request.url.path.startswith("/api/"):
            provided = request.headers.get("x-umbral-desktop-token", "")
            origin = request.headers.get("origin")
            if not hmac.compare_digest(provided, token) or origin not in {None, f"http://{expected_host}"}:
                return JSONResponse({"detail": "Sesión de escritorio requerida."}, status_code=403)
        return await call_next(request)

    @app.get("/api/v1/desktop/status")
    def desktop_status():
        return jobs.get_status()

    @app.post("/api/v1/desktop/{operation}")
    def desktop_operation(operation: str):
        if operation == "shutdown":
            jobs.stop()
            server.should_exit = True
            return {"ok": True}
        if operation not in {"update", "reclassify"}:
            raise HTTPException(404, "Operación desconocida.")
        result = jobs.start(operation)
        if result is None:
            raise HTTPException(409, "Ya hay una tarea de datos en curso.")
        return result

    app.mount("/", StaticFiles(directory=str(resources / "web"), html=True), name="web")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    threading.Thread(target=watch_parent, args=(config.get("parentPid", 0), jobs, server), daemon=True).start()

    async def run():
        task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started and not task.done():
            await asyncio.sleep(0.01)
        if server.started:
            print(json.dumps({"type": "ready", "port": port}), flush=True)
            async def refresh_loop():
                while not server.should_exit:
                    if app.state.services.settings.offline:
                        return
                    await asyncio.to_thread(discover_public_api, app.state.services,
                                            config.get("publicConfigUrl", "https://site-umbral.web.app/public-config.json"))
                    jobs.start("update")
                    await asyncio.sleep(900)

            refresh_task = asyncio.create_task(refresh_loop())
        else:
            refresh_task = None
        await task
        if refresh_task:
            refresh_task.cancel()
        jobs.stop()

    asyncio.run(run())


def main():
    # Set these before transformers/torch imports; installed clients never fetch models.
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", USE_TF="0", TOKENIZERS_PARALLELISM="false")
    if len(sys.argv) > 1 and sys.argv[1] == "--pipeline":
        from umbral_pipeline.cli import main as pipeline_main

        return pipeline_main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "--laya-smoke":
        from umbral_pipeline.classify.laya_clf import LayaClassifier

        clf = LayaClassifier(model_dir=Path(sys.argv[2]), log=lambda _: None)
        preds = clf.predict([{"articleId": "smoke", "title": "Sismo de magnitud 5,1 sacude el sur de Panamá"}])
        print(json.dumps({"classifier": clf.info(), "prediction": preds[0]}, ensure_ascii=False), flush=True)
        return 0 if preds[0]["classifier"] == "laya" and preds[0]["category"] == "eventos_naturales" else 1
    config = json.loads(sys.stdin.readline())
    serve(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
