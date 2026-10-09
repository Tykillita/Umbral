"""Controles sintéticos de procedencia: reutilizar evidencia no inventa ni altera juicios."""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

from umbral_pipeline.util import read_jsonl, sha256_file, write_jsonl

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def rebind_case(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    spec = importlib.util.spec_from_file_location("rebind_label_sheets", ROOT / "eval/rebind_label_sheets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source, target, labels = (tmp_path / name for name in ("source", "target", "labels"))
    for path in (source, target, labels):
        path.mkdir()
    for path in (source, target):
        write_jsonl(path / "articles.jsonl", [{"articleId": "fx_a", "title": "Titular de control"},
                                             {"articleId": "fx_b", "title": "Otro titular de control"}])
        write_jsonl(path / "indicators.jsonl", [])
        write_jsonl(path / "predictions.jsonl", [{"articleId": "fx_a", "category": "economia", "geoRelevance": "panama"}])
        write_jsonl(path / "clusters.jsonl", [{"clusterId": "fx_topic", "memberArticleIds": ["fx_a", "fx_b"]}])
    manifest = {"files": {name: {"sha256": sha256_file(target / name)} for name in ("articles.jsonl", "indicators.jsonl")}}
    monkeypatch.setattr(module, "verified_manifest", lambda path: {**manifest, "snapshotId": path.name})
    cls = {"id": "fx_a", "articleId": "fx_a", "title": "Titular de control", "predictedCategory": "otro",
           "predictedGeo": "otro", "label": None, "labeler": None, "labelMethod": "human_pending"}
    pair = {"id": "fx_pair", "a": "fx_a", "b": "fx_b", "titleA": "Titular de control", "titleB": "Otro titular de control",
            "predictedSameCluster": False, "sameEvent": None, "labelMethod": "human_pending"}
    claim = {"id": "fx_claim", "topicId": "fx_topic", "snapshotId": "source", "supported": None, "citationCorrect": None,
             "text": "La fuente reporta: Titular de control", "labelMethod": "human_pending",
             "citations": [{"evidenceId": "fx_a", "field": "title", "passage": "Titular de control"}]}
    for name, row in (("cls_sample", cls), ("pairs_sample", pair), ("claims_sample", claim), ("claims_review", claim)):
        write_jsonl(labels / f"{name}.source.jsonl", [row])
    for name, row_id in (("clasificacion", "fx_a"), ("pares", "fx_pair"), ("afirmaciones", "fx_claim")):
        with (labels / f"{name}.source.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "texto", "predicción", "juicio_humano", "comentario"])
            writer.writeheader()
            writer.writerow({"id": row_id, "texto": "Texto original", "predicción": "original",
                             "juicio_humano": "", "comentario": "Comentario sintético conservado"})
    return module, source, target, labels, manifest


def test_rebind_preserves_source_bytes_citations_and_pending_judgments(rebind_case):
    module, source, target, labels, _ = rebind_case
    hashes = {path.name: sha256_file(path) for path in labels.iterdir()}
    receipt = module.rebind_label_sheets(source, target, labels)
    assert receipt["method"] == "identical_evidence_rebind"
    assert all(sha256_file(labels / name) == value for name, value in hashes.items())
    claim = next(read_jsonl(labels / "claims_review.target.jsonl"))
    assert claim["supported"] is None and claim["labelMethod"] == "human_pending"
    assert claim["citations"] == [{"evidenceId": "fx_a", "field": "title", "passage": "Titular de control"}]
    assert claim["sourceSnapshotId"] == "source" and claim["snapshotId"] == "target"
    sample = next(read_jsonl(labels / "cls_sample.target.jsonl"))
    assert sample["predictedCategory"] == "economia" and sample["label"] is None
    with (labels / "clasificacion.target.csv").open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["juicio_humano"] == "" and row["comentario"] == "Comentario sintético conservado"


def test_changed_evidence_or_citation_rejects_rebind_before_writing(rebind_case):
    module, source, target, labels, manifest = rebind_case
    module.verified_manifest = lambda path: {**manifest, "snapshotId": path.name,
                                           "files": {**manifest["files"], "articles.jsonl": {"sha256": path.name}}}
    with pytest.raises(ValueError, match="cambió"):
        module.rebind_label_sheets(source, target, labels)
    assert not list(labels.glob("*.target.*"))
    module.verified_manifest = lambda path: {**manifest, "snapshotId": path.name}
    claim_path = labels / "claims_sample.source.jsonl"
    row = next(read_jsonl(claim_path))
    row["citations"][0]["passage"] = "Una cita inventada para el control"
    write_jsonl(claim_path, [row])
    with pytest.raises(ValueError, match="pasaje"):
        module.rebind_label_sheets(source, target, labels)
    assert not list(labels.glob("*.target.*"))


def test_existing_destination_sheets_are_never_overwritten(rebind_case):
    module, source, target, labels, _ = rebind_case
    module.rebind_label_sheets(source, target, labels)
    hashes = {path.name: sha256_file(path) for path in labels.iterdir()}
    with pytest.raises(ValueError, match="sobrescriben"):
        module.rebind_label_sheets(source, target, labels)
    assert hashes == {path.name: sha256_file(path) for path in labels.iterdir()}
