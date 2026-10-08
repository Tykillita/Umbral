"""Descarga controlada de snapshots: hashes/referencias, fallo y sustitución atómica."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from umbral_api.config import Settings
from umbral_api.services import Services
from umbral_api.snapshot import load_corpus, prediction_input_hash, sha256_file

from .conftest import make_settings


def snapshot_for_transport_test(fixture_dir: Path, target: Path, *, change="") -> Path:
    """Copia de laboratorio del CURRENT real verificado; no ejecuta ni simula Laya."""
    corpus = load_corpus(Settings(persistence="memory", allow_fixture=False, strict_integrity=True))
    assert corpus.classifier == "laya" and not corpus.contains_fixtures
    shutil.copytree(corpus.path, target)
    articles = [json.loads(line) for line in (target / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
    if change:
        # Entrada normalizada exactamente igual a la original: mantiene válida la
        # predicción real de Laya. Solo cambia la serialización/hash del snapshot.
        articles[0]["title"] += " " * len(change)
        (target / "articles.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in articles), encoding="utf-8")
    predictions = [json.loads(line) for line in (target / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    titles = {row["articleId"]: row["title"] for row in articles}
    for prediction in predictions:
        prediction["inputHash"] = prediction_input_hash(titles[prediction["articleId"]])
    (target / "predictions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in predictions), encoding="utf-8")
    _rehash(target)
    return target


def _rehash(target):
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    manifest["containsFixtures"] = False
    for name in set(manifest["files"]) | {"quality_report.json"}:
        manifest["files"][name] = {"sha256": sha256_file(target / name), "bytes": (target / name).stat().st_size}
    hashes = "".join(manifest["files"][name]["sha256"] for name in ("articles.jsonl", "indicators.jsonl", "predictions.jsonl", "clusters.jsonl"))
    manifest["snapshotId"] = manifest["cutoffUtc"][:10].replace("-", "") + "-" + hashlib.sha256(hashes.encode()).hexdigest()[:8]
    manifest["classifier"]["articlesSha256"] = manifest["files"]["articles.jsonl"]["sha256"]
    predictions = [json.loads(line) for line in (target / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    text = "".join(f"{row['articleId']}:{row['inputHash']}\n" for row in sorted(predictions, key=lambda row: row["articleId"]))
    manifest["classifier"]["predictionsInputSha256"] = hashlib.sha256(text.encode()).hexdigest()
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def install_mock_feed(monkeypatch, snapshot, *, mutate=None, corrupt=None, redirect=False):
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    sid = manifest["snapshotId"]
    prefix = "snapshots/" + sid + "/"
    descriptor = {"schemaVersion": 1, "snapshotId": sid, "publishedAt": "2026-10-07T11:17:00Z",
                  "manifest": {"path": prefix + "manifest.json", "sha256": sha256_file(snapshot / "manifest.json")},
                  "files": [{"path": prefix + name, "sha256": meta["sha256"], "sizeBytes": (snapshot / name).stat().st_size}
                            for name, meta in manifest["files"].items()]}
    if mutate:
        mutate(descriptor)
    paths = []

    def handle(request):
        paths.append(str(request.url))
        if request.url.path == "/data/current.json":
            return httpx.Response(302, headers={"location": "https://evil.example/descriptor"}) if redirect else httpx.Response(200, json=descriptor)
        name = request.url.path.rsplit("/", 1)[-1]
        content = (snapshot / name).read_bytes()
        if name == corrupt:
            content += b"tampered"
        return httpx.Response(200, content=content)

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    return descriptor, paths


def service(fixture_dir, tmp_path):
    settings = make_settings(fixture_dir, snapshots_root=tmp_path / "download", snapshot_feed_url="https://feed.example/data/current.json")
    return Services(settings)


def test_feed_installs_verified_snapshot_and_inflight_request_keeps_old_state(fixture_dir, tmp_path, monkeypatch):
    new = snapshot_for_transport_test(fixture_dir, tmp_path / "remote", change="Actualización de laboratorio")
    descriptor, paths = install_mock_feed(monkeypatch, new)
    svc = service(fixture_dir, tmp_path)
    inflight = svc.request_view()
    old = inflight.corpus.snapshot_id
    assert svc.snapshot_feed.refresh() is True
    assert svc.corpus.snapshot_id == descriptor["snapshotId"] != old
    assert svc.engine.corpus is svc.corpus and set(svc.bases) == set(svc.corpus.clusters)
    assert inflight.corpus.snapshot_id == old and inflight.engine.corpus is inflight.corpus
    assert (svc.settings.snapshots_root / "CURRENT").read_text(encoding="utf-8").strip() == svc.corpus.snapshot_id
    assert all(url.startswith("https://feed.example/data/") for url in paths)
    assert svc.snapshot_feed.refresh() is False and svc.snapshot_feed.last_error is None


@pytest.mark.parametrize("failure", ["hash", "traversal", "other_origin", "redirect", "duplicate", "fixtures", "baseline"])
def test_feed_failures_preserve_last_snapshot_and_pointer(fixture_dir, tmp_path, monkeypatch, failure):
    new = snapshot_for_transport_test(fixture_dir, tmp_path / "remote", change="Nuevo corte de laboratorio")
    if failure in {"fixtures", "baseline"}:
        manifest = json.loads((new / "manifest.json").read_text(encoding="utf-8"))
        if failure == "fixtures":
            manifest["containsFixtures"] = True
        else:
            manifest["classifier"]["classifier"] = "baseline"
        (new / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    def mutate(descriptor):
        if failure == "traversal":
            descriptor["files"][0]["path"] = "../../outside.json"
        if failure == "other_origin":
            descriptor["files"][0]["path"] = "https://evil.example/article"
        if failure == "duplicate":
            descriptor["files"].append(descriptor["files"][0])
    _, paths = install_mock_feed(monkeypatch, new, mutate=mutate, corrupt="articles.jsonl" if failure == "hash" else None,
                                 redirect=failure == "redirect")
    svc = service(fixture_dir, tmp_path)
    old = svc._state
    assert svc.snapshot_feed.refresh() is False
    assert svc._state is old and svc.snapshot_feed.last_error
    assert not (svc.settings.snapshots_root / "CURRENT").exists()
    assert not any("evil.example" in path for path in paths)
    assert not list(svc.settings.snapshots_root.glob(".download-*"))


def test_feed_rejects_rehashed_invalid_references_and_undeclared_fixture(fixture_dir, tmp_path, monkeypatch):
    new = snapshot_for_transport_test(fixture_dir, tmp_path / "remote", change="Laboratorio")
    clusters = [json.loads(line) for line in (new / "clusters.jsonl").read_text(encoding="utf-8").splitlines()]
    clusters[0]["memberArticleIds"].append("missing-article")
    (new / "clusters.jsonl").write_text("".join(json.dumps(row) + "\n" for row in clusters), encoding="utf-8")
    _rehash(new)
    install_mock_feed(monkeypatch, new)
    svc = service(fixture_dir, tmp_path)
    assert not svc.snapshot_feed.refresh()
    assert svc.corpus.path == fixture_dir
    with pytest.raises(RuntimeError, match="referencias"):
        load_corpus(replace(make_settings(new), strict_integrity=True))


def test_undeclared_fixture_cannot_be_activated_even_with_valid_hashes(fixture_dir, tmp_path):
    new = snapshot_for_transport_test(fixture_dir, tmp_path / "remote")
    articles = [json.loads(line) for line in (new / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
    articles[0]["dataOrigin"] = "fixture"
    (new / "articles.jsonl").write_text("".join(json.dumps(row) + "\n" for row in articles), encoding="utf-8")
    _rehash(new)
    svc = service(fixture_dir, tmp_path)
    old = svc._state
    with pytest.raises(RuntimeError, match="fixture"):
        svc.activate_snapshot(new)
    assert svc._state is old


def test_direct_activation_cannot_replace_laya_with_baseline(fixture_dir, tmp_path):
    new = snapshot_for_transport_test(fixture_dir, tmp_path / "remote")
    manifest = json.loads((new / "manifest.json").read_text(encoding="utf-8"))
    manifest["classifier"]["classifier"] = "baseline"
    (new / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    svc = service(fixture_dir, tmp_path)
    old = svc._state
    with pytest.raises(RuntimeError, match="Laya"):
        svc.activate_snapshot(new)
    assert svc._state is old


def test_stale_snapshot_warning_uses_utc_age(fixture_dir, tmp_path):
    settings = make_settings(fixture_dir, now_override="2020-01-01T00:00:00Z")
    assert Services(settings).health().snapshot_stale
