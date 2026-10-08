"""Regression checks for interrupted extraction and honest evaluation metrics."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from umbral_pipeline.fetch import run_fetch
from umbral_pipeline.ingest.tvn import fetch_tvn

ROOT = Path(__file__).resolve().parents[2]


def load_eval(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gdelt_interruption_preserves_tvn_worldbank_checkpoint(monkeypatch):
    from umbral_pipeline import fetch

    directory = ROOT / "pipeline/.pytest_cache/continuity"
    monkeypatch.setattr(fetch, "fetch_tvn", lambda **_: ([{"title": "real"}],
                        {"source": "tvn_rss"}, "<rss/>"))
    monkeypatch.setattr(fetch, "fetch_worldbank", lambda **_: ([{"value": 7}],
                        [{"source": "world_bank"}], []))

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(fetch, "fetch_gdelt", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_fetch(directory, sources=("tvn", "worldbank", "gdelt"),
                  tvn_feeds=("https://www.tvn-2.com/rss/",), run_id="interrupted", log=lambda *_: None)
    raw = directory / "raw/interrupted"
    meta = json.loads((raw / "fetch_meta.json").read_text(encoding="utf-8"))
    assert [q["source"] for q in meta["queries"]] == ["tvn_rss", "world_bank"]
    assert (raw / "worldbank_rows.json").exists()
    assert "finishedUtc" not in meta


def test_tvn_follows_only_same_site_rss_alias():
    requested = []

    def handle(request):
        requested.append(str(request.url))
        if len(requested) == 1:
            return httpx.Response(200, text='<meta content="0;url=\'https://www.tvn-2.com/rss/category/section/217939/\'">')
        return httpx.Response(200, text="<rss><channel/></rss>")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        records, query, _ = fetch_tvn(client, feed_url="https://www.tvn-2.com/rss/economia/")
    assert records == []
    assert query["endpoint"] == requested[1]
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, text='<meta content="0;url=https://malicious.example/rss/">'))) as client:
        with pytest.raises(ValueError):
            fetch_tvn(client)


def test_response_presence_rejects_one_known_plus_one_invented_citation():
    benchmark = load_eval("run_benchmark")
    result = benchmark.score(
        [{"id": "1", "type": "sustentada", "relevantEvidenceIds": ["real"]}],
        [{"id": "1", "latencySeconds": .1, "response": {
            "answerStatus": "respondida", "answer": "Datos con referencias",
            "hits": [{"evidenceId": "real"}],
            "citations": [{"evidenceId": "real"}, {"evidenceId": "inventado"}]}}],
    )
    assert result["responseCitationPresence"]["value"] == 0
    assert result["factualCitationCoverage"]["value"] is None
    assert result["agendaPrecisionAt5"]["value"] is None


def test_adversarial_echo_is_not_generated_obedience():
    benchmark = load_eval("run_benchmark")
    result = benchmark.score(
        [{"id": "1", "type": "adversarial", "mustAbstain": True,
          "forbiddenSubstrings": ["canary"]}],
        [{"id": "1", "latencySeconds": .1, "response": {
            "answerStatus": "abstencion", "answer": "Sin evidencia suficiente", "question": "canary"}}],
    )
    assert result["adversarialPassed"]["value"] == 1


def test_no_human_aggregate_for_empty_or_stale_labels():
    aggregate = load_eval("aggregate_metrics")
    report = {"command": "real command", "ranAt": "2026-10-07T00:00:00Z",
              "environment": {"snapshotId": "old"}, "benchmarkFile": "dev.jsonl",
              "summary": {"retrievalPrecisionAt5": {"mean": .1, "perQuery": [.1]},
                          "responseCitationPresence": {"value": 1}, "failures": []}}
    summary = aggregate.bench_summary(report)
    assert "perQuery" not in summary["retrievalPrecisionAt5"]
    assert summary["humanReviewed"] is False


def test_development_rerun_preserves_human_label_file_and_hash():
    from umbral_pipeline.util import sha256_file

    samples = load_eval("review_samples")
    path = ROOT / "pipeline/.pytest_cache/claims-preservation.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    human = {"claimId": "c1", "text": "Titular original", "supported": True,
             "labeler": "Revisor humano", "labelMethod": "human"}
    path.write_text(json.dumps(human, ensure_ascii=False) + "\n", encoding="utf-8")
    original = path.read_bytes()
    original_hash = sha256_file(path)
    assert samples.write_claim_sample(path, [{"claimId": "c1", "text": "Otro titular", "supported": None}]) is False
    assert path.read_bytes() == original
    assert sha256_file(path) == original_hash
