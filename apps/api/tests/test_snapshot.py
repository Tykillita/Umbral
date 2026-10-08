"""Carga del snapshot e integridad (manifest SHA-256 y hash de predicciones de Laya)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from umbral_api.config import Settings, repo_root
from umbral_api.models import DataMode
from umbral_api.snapshot import load_corpus

from .conftest import make_settings


def _copy(fixture_dir: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "snap"
    shutil.copytree(fixture_dir, dst)
    return dst


def test_fixture_loads_verified_and_labelled(fixture_dir):
    c = load_corpus(make_settings(fixture_dir))
    assert c.data_mode == DataMode.fixture and c.contains_fixtures and c.provisional
    assert c.integrity.manifest_verified and c.integrity.predictions_hash_verified is True
    assert c.integrity.errors == []
    assert c.integrity.predictions_sha256 == c.manifest["classifier"]["predictionsInputSha256"]
    assert any("fixture" in n.lower() for n in c.notes)


def test_tampered_file_breaks_manifest_hash(fixture_dir, tmp_path):
    d = _copy(fixture_dir, tmp_path)
    p = d / "articles.jsonl"
    p.write_text(p.read_text(encoding="utf-8").replace("Chiriquí", "Veraguas", 1), encoding="utf-8")
    c = load_corpus(make_settings(d))
    assert not c.integrity.manifest_verified
    assert any("articles.jsonl" in e for e in c.integrity.errors)


def test_predictions_not_matching_snapshot_are_detected(fixture_dir, tmp_path):
    d = _copy(fixture_dir, tmp_path)
    p = d / "predictions.jsonl"
    rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    rows[0]["inputHash"] = "0" * 64
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    c = load_corpus(make_settings(d))
    assert c.integrity.predictions_hash_verified is False
    assert any("predicci" in e.lower() or "inputHash" in e for e in c.integrity.errors)


def test_strict_integrity_refuses_tampered_snapshot(fixture_dir, tmp_path):
    d = _copy(fixture_dir, tmp_path)
    (d / "clusters.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_corpus(replace(make_settings(d), strict_integrity=True))


def test_missing_snapshot_without_fixture_is_an_error(tmp_path):
    s = Settings(snapshots_root=tmp_path / "nada", allow_fixture=False)
    with pytest.raises(FileNotFoundError):
        load_corpus(s)


def test_null_dates_and_missing_indicator_values_are_kept(fixture_dir):
    c = load_corpus(make_settings(fixture_dir))
    assert any(a.published_at is None for a in c.articles.values())  # no se rellena
    missing = [i for i in c.indicators.values() if i.is_missing]
    assert missing and all(i.value is None for i in missing)  # nulos conservados, nunca 0


def test_real_snapshot_from_datos_if_present_passes_integrity():
    root = repo_root() / "data" / "snapshots"
    dirs = [d for d in root.glob("*") if (d / "manifest.json").exists()] if root.exists() else []
    if not dirs:
        pytest.skip("aún no hay snapshot en data/snapshots")
    c = load_corpus(Settings(snapshot_dir=sorted(dirs)[-1], persistence="memory"))
    assert c.integrity.manifest_verified, c.integrity.errors
    assert c.integrity.predictions_hash_verified is True, c.integrity.errors


def test_current_pointer_serves_verified_real_laya_snapshot_if_present():
    root = repo_root() / "data" / "snapshots"
    pointer = root / "CURRENT"
    if not pointer.exists():
        pytest.skip("Aún no se seleccionó el snapshot público CURRENT.")
    current = pointer.read_text(encoding="utf-8").strip()
    corpus = load_corpus(Settings(snapshots_root=root, allow_fixture=False, strict_integrity=True, persistence="memory"))
    assert corpus.snapshot_id == current
    assert not corpus.contains_fixtures and corpus.classifier == "laya"
    assert corpus.integrity.manifest_verified and corpus.integrity.predictions_hash_verified is True


def test_current_snapshot_templates_are_valid_for_all_topics_if_present():
    from umbral_api.drafts import build_pack, build_template_package, validate_package
    from umbral_api.services import Services

    root = repo_root() / "data" / "snapshots"
    if not (root / "CURRENT").exists():
        pytest.skip("Aún no se seleccionó CURRENT.")
    service = Services(Settings(snapshots_root=root, allow_fixture=False, strict_integrity=True,
        persistence="memory", offline=True))
    failures = []
    for base in service.bases.values():
        score = service._score(base, service._impact_for(base, None))
        package = build_template_package(base, score=score.total, band=score.band.value, status=base.status_for(False)[0].value)
        _, report = validate_package(package, build_pack(base))
        if not report.ok:
            failures.append((base.id, [i.code for i in report.issues if i.severity == "error"]))
    assert service.bases
    assert not failures, failures[:10]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "partial"])
def test_prediction_coverage_is_required_even_with_non_strict_manifest(fixture_dir, tmp_path, mutation):
    d = _copy(fixture_dir, tmp_path)
    p = d / "predictions.jsonl"
    rows = p.read_text(encoding="utf-8").splitlines()
    changed = [] if mutation == "missing" else (rows + rows[:1] if mutation == "duplicate" else rows[1:])
    p.write_text("\n".join(changed) + "\n", encoding="utf-8")
    c = load_corpus(make_settings(d))
    assert c.integrity.predictions_hash_verified is False


def test_invalid_current_pointer_does_not_fall_back_to_another_snapshot(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    (root / "CURRENT").write_text("missing-snapshot")
    with pytest.raises(FileNotFoundError, match="CURRENT"):
        load_corpus(Settings(snapshots_root=root))


def test_metrics_must_belong_to_the_served_snapshot(fixture_dir, tmp_path):
    snapshot = _copy(fixture_dir, tmp_path)
    metric_path = snapshot / "metrics.json"
    metric_path.write_text(json.dumps({"snapshotId": "another-snapshot", "factualCitationCoverage": 1.0}))
    assert load_corpus(make_settings(snapshot)).metrics is None
    sid = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))["snapshotId"]
    metric_path.write_text(json.dumps({"snapshotId": sid, "factualCitationCoverage": 1.0}))
    assert load_corpus(make_settings(snapshot)).metrics["snapshotId"] == sid
