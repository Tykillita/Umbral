import importlib.util
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from umbral_pipeline.classify.laya_clf import PINNED_REVISION
from umbral_pipeline.util import sha256_file

DESKTOP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_sidecar", DESKTOP / "sidecar.py")
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)


def test_manual_upgrade_backs_up_wal_database_and_preserves_preferences(tmp_path):
    with sqlite3.connect(tmp_path / "umbral.sqlite") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE cases(id TEXT PRIMARY KEY, body TEXT)")
        db.execute("INSERT INTO cases VALUES('case-1','texto original')")
    (tmp_path / "config.json").write_text(json.dumps({"appVersion": "0.0.1", "preference": "value"}))
    sidecar.backup_database(tmp_path, "0.1.0")
    backups = list((tmp_path / "backups").glob("*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("SELECT body FROM cases WHERE id='case-1'").fetchone()[0] == "texto original"
    assert json.loads((tmp_path / "config.json").read_text())["preference"] == "value"
    sidecar.backup_database(tmp_path, "0.1.0")
    assert len(list((tmp_path / "backups").glob("*.sqlite"))) == 1


@dataclass(frozen=True)
class DiscoverySettings:
    public_api_url: str | None = None


@pytest.mark.parametrize("url,expected", [
    ("https://umbral-api.onrender.com", True),
    ("https://evil.example", False),
    ("http://umbral-api.onrender.com", False),
    ("https://token@umbral-api.onrender.com", False),
    ("https://umbral-api.onrender.com/?secret=1", False),
    ("https://umbral-api.onrender.com.evil.example", False),
])
def test_discovery_accepts_only_public_https_render_endpoint(monkeypatch, url, expected):
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"schemaVersion": 1, "apiUrl": url})), **kwargs))
    services = SimpleNamespace(settings=DiscoverySettings())
    assert sidecar.discover_public_api(services, "https://site-umbral.web.app/public-config.json") is expected
    assert services.settings.public_api_url == (url if expected else None)


def test_news_refresh_runs_immediately_then_once_per_interval():
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    assert sidecar.news_refresh_due(None, now=now)
    assert not sidecar.news_refresh_due(now.isoformat(), last_success_at=now.isoformat(),
                                       now=now + timedelta(hours=23, minutes=59))
    assert sidecar.news_refresh_due(now.isoformat(), last_success_at=now.isoformat(),
                                    now=now + timedelta(hours=24))
    assert sidecar.news_refresh_due("invalid", now=now)


@pytest.mark.parametrize("retry_count,minutes", [(1, 15), (2, 30), (3, 60), (4, 180), (8, 180)])
def test_news_refresh_retries_failed_attempts_with_capped_backoff(retry_count, minutes):
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    attempt = now.isoformat()
    just_before = now + timedelta(minutes=minutes, seconds=-1)
    retry_time = now + timedelta(minutes=minutes)

    assert not sidecar.news_refresh_due(attempt, retry_count=retry_count, now=just_before)
    assert sidecar.news_refresh_due(attempt, retry_count=retry_count, now=retry_time)


def test_failure_after_daily_run_retries_without_losing_daily_schedule():
    success = datetime(2026, 10, 8, 12, tzinfo=UTC)
    failed_attempt = success + timedelta(hours=24)
    now = failed_attempt + timedelta(minutes=15)

    assert not sidecar.news_refresh_due(failed_attempt.isoformat(), last_success_at=success.isoformat(),
                                        retry_count=1, now=failed_attempt + timedelta(minutes=14))
    assert sidecar.news_refresh_due(failed_attempt.isoformat(), last_success_at=success.isoformat(),
                                    retry_count=1, now=now)


def test_desktop_scheduler_starts_one_news_job_and_persists_its_next_run(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "CURRENT").write_text("20261007-e704e952\n", encoding="utf-8")
    app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(
        settings=SimpleNamespace(offline=False),
        corpus=SimpleNamespace(snapshot_id="20261007-e704e952"),
    )))
    started = []

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            started.append({"target": target, "args": args, "daemon": daemon})

        def start(self):
            return None

    monkeypatch.setattr(sidecar.threading, "Thread", FakeThread)
    jobs = sidecar.DesktopJobs(app, tmp_path / "resources", tmp_path, "https://example.test/feed.json")

    first = jobs.maybe_start_scheduled_news_refresh()
    second = jobs.maybe_start_scheduled_news_refresh()

    assert first["operation"] == "news"
    assert second is None
    assert len(started) == 1
    assert started[0]["args"] == ("news",)
    assert started[0]["daemon"] is True
    state = json.loads((tmp_path / "news-refresh.json").read_text(encoding="utf-8"))
    assert state["lastAttemptAt"].endswith("Z")
    status = jobs.get_status()["newsAutomation"]
    assert status["enabled"] is True
    assert status["intervalHours"] == 24
    assert status["nextRunAt"] is not None


def test_desktop_news_scheduler_stays_paused_offline(tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "CURRENT").write_text("20261007-e704e952\n", encoding="utf-8")
    app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(
        settings=SimpleNamespace(offline=True),
        corpus=SimpleNamespace(snapshot_id="20261007-e704e952"),
    )))
    jobs = sidecar.DesktopJobs(app, tmp_path / "resources", tmp_path, "https://example.test/feed.json")

    status = jobs.get_status()["newsAutomation"]

    assert status["enabled"] is False
    assert status["nextRunAt"] is None
    assert jobs.maybe_start_scheduled_news_refresh() is None


def _jobs_fixture(tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "CURRENT").write_text("20261007-e704e952\n", encoding="utf-8")
    app = SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(
        settings=SimpleNamespace(offline=False),
        corpus=SimpleNamespace(snapshot_id="20261007-e704e952"),
    )))
    return sidecar.DesktopJobs(app, tmp_path / "resources", tmp_path, "https://example.test/feed.json")


def test_news_worker_stderr_is_saved_when_candidate_fails(monkeypatch, tmp_path):
    jobs = _jobs_fixture(tmp_path)

    class FailedProcess:
        stdout = ()

        def __init__(self, *_args, stderr, **_kwargs):
            stderr.write("RuntimeError: calibrated model allocation failed\n")
            stderr.flush()

        @staticmethod
        def wait():
            return 2

    monkeypatch.setattr(sidecar.subprocess, "Popen", FailedProcess)

    try:
        jobs._discover_news()
    except RuntimeError as exc:
        assert "news-worker.log" in str(exc)
    else:
        raise AssertionError("el candidato fallido debe conservar el snapshot y reportar su diagnóstico")

    log = (tmp_path / "diagnostics" / "news-worker.log").read_text(encoding="utf-8")
    assert "calibrated model allocation failed" in log


def test_news_failure_persists_sidecar_traceback_outside_smoke_mode(monkeypatch, tmp_path):
    jobs = _jobs_fixture(tmp_path)
    monkeypatch.delenv("UMBRAL_DESKTOP_SMOKE", raising=False)

    def fail_news():
        raise RuntimeError("captured news failure")

    monkeypatch.setattr(jobs, "_discover_news", fail_news)

    jobs._run("news")

    traceback_log = (tmp_path / "diagnostics" / "news-exception.log").read_text(encoding="utf-8")
    assert "captured news failure" in traceback_log
    state = json.loads((tmp_path / "news-refresh.json").read_text(encoding="utf-8"))
    assert state["lastWarning"] == "La búsqueda automática no superó la validación; se conservó el snapshot anterior."
    assert state["retryCount"] == 1


def _write_calibrated_bundle_fixture(resources: Path) -> tuple[dict, dict]:
    model_dir = resources / "laya"
    model_dir.mkdir(parents=True)
    weights = model_dir / "model.safetensors"
    weights.write_bytes(b"trained-laya-weights")
    profile_data = {
        "schemaVersion": "1.0.0",
        "profileId": "laya-cal-test",
        "modelVersion": "laya-ft-test",
        "method": "temperature-scaling",
        "temperature": 1.8,
        "threshold": 0.57,
        "evaluationKind": "agent_review",
        "fit": {"calibrationExamples": 151, "validationExamples": 101, "testGate": {"passed": True}},
    }
    profile_path = model_dir / "umbral-calibration.json"
    profile_path.write_text(json.dumps(profile_data), encoding="utf-8")
    profile_sha = sha256_file(profile_path)
    (model_dir / "umbral-model.json").write_text(json.dumps({
        "modelVersion": "laya-ft-test", "weightsSha256": sha256_file(weights),
    }), encoding="utf-8")
    snapshot_id = "20261009-12345678"
    snapshots = resources / "snapshots"
    (snapshots / snapshot_id).mkdir(parents=True)
    (snapshots / "CURRENT").write_text(snapshot_id + "\n", encoding="utf-8")
    classifier = {
        "classifier": "laya", "calibrated": True, "modelVersion": "laya-ft-test",
        "calibrationProfileId": "laya-cal-test", "calibrationProfileSha256": profile_sha,
    }
    state = {"manifest": {"classifier": classifier, "counts": {"articlesValid": 1}},
             "predictions": [{"calibrated": True, "modelVersion": "laya-ft-test",
                              "calibrationProfileId": "laya-cal-test"}]}
    bundle = {"layaRevision": PINNED_REVISION, "modelWeightsSha256": sha256_file(weights),
              "calibrated": True, "modelVersion": "laya-ft-test", "snapshotId": snapshot_id,
              "calibrationProfileId": "laya-cal-test", "calibrationProfileSha256": profile_sha}
    return bundle, state


def test_packaged_desktop_requires_exact_calibrated_model_and_seed_snapshot(monkeypatch, tmp_path):
    from umbral_pipeline import refresh

    bundle, state = _write_calibrated_bundle_fixture(tmp_path)
    monkeypatch.setattr(refresh, "load_verified", lambda _snapshot: state)

    sidecar.verify_bundle_calibration(tmp_path, bundle)

    mismatched = {**state, "manifest": {**state["manifest"], "classifier": {
        **state["manifest"]["classifier"], "calibrationProfileId": "different-profile",
    }}}
    monkeypatch.setattr(refresh, "load_verified", lambda _snapshot: mismatched)
    with pytest.raises(ValueError, match="artefacto Laya calibrado exacto"):
        sidecar.verify_bundle_calibration(tmp_path, bundle)
