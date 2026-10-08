import importlib.util
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

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
