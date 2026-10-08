"""Executable synthetic controls for evaluation CLIs; never human/domain metrics.

Builds explicit fixture snapshots with controlled predictions and known labels,
then checks classification, probability quality, pairs, agenda, claims and tamper
rejection. Does not download/load models or contact a provider.
"""
from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from umbral_pipeline.classify.baseline import BaselineClassifier
from umbral_pipeline.fixtures import fixture_indicators, fixture_news
from umbral_pipeline.snapshot import export_snapshot, verify_snapshot
from umbral_pipeline.util import iso_z, sha256_file, write_json, write_jsonl
from umbral_pipeline.validate import normalize_record

ROOT = Path(__file__).resolve().parents[1]


def fixture_snapshots(directory: Path) -> tuple[Path, Path, list[dict]]:
    cutoff = datetime(2026, 10, 7, 8, tzinfo=UTC)
    articles = []
    for raw in fixture_news(cutoff):
        article, _ = normalize_record(raw, window_start=cutoff-timedelta(days=30), cutoff=cutoff,
                                      extracted_default=iso_z(cutoff), is_fixture=True)
        if article:
            articles.append(article)
        if len(articles) == 4:
            break
    predictions = BaselineClassifier().predict(articles, predicted_at=cutoff)
    a, b, c, d = [r["articleId"] for r in articles]
    clusters = [{"clusterId": "synthetic_A", "memberArticleIds": [a, b, d]},
                {"clusterId": "synthetic_B", "memberArticleIds": [c]}]
    snapshots = []
    for classifier_name in ("laya", "baseline"):
        controlled = copy.deepcopy(predictions)
        for index, prediction in enumerate(controlled):
            prediction.update({"classifier": classifier_name, "modelId": f"synthetic-control-{classifier_name}",
                               "modelVersion": "synthetic-v1", "category": "economia", "geoRelevance": "panama",
                               "probabilities": {"economia": 1.0}, "synthetic": True})
            if index == 0:
                confidence = .9 if classifier_name == "laya" else .6
                prediction.update(probabilities={"economia": confidence, "turismo": 1-confidence}, probability=confidence)
            if index == 1:
                prediction["geoRelevance"] = "regional"
                if classifier_name == "laya":
                    prediction.update(category="turismo", probabilities={"economia": .2, "turismo": .8}, probability=.8)
                else:
                    prediction.update(probabilities={"economia": .7, "turismo": .3}, probability=.7)
        snapshot = export_snapshot(directory, cutoff=cutoff, window={"days": 30}, queries=[], articles=articles,
                                   indicators=fixture_indicators(iso_z(cutoff)), predictions=controlled, clusters=clusters,
                                   invalid=[], quality={"clusters": {"linkMethods": {"synthetic_control": True}}},
                                   classifier_info={"classifier": classifier_name, "modelVersion": "synthetic-v1",
                                                    "note": "Predicciones CONTROLADAS: no se ejecutó Laya ni se mide desempeño de dominio."},
                                   events_geojson=None, contains_fixtures=True,
                                   provisional_reasons=["synthetic_control_not_human_or_model_metrics"],
                                   sources_extracted={}, transformations=["synthetic_control"], set_current=False)
        assert verify_snapshot(snapshot)[0]
        snapshots.append(snapshot)
    return snapshots[0], snapshots[1], articles


def verify(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    laya_control, baseline_control, articles = fixture_snapshots(directory / "fixture-data")
    sid = laya_control.name
    ids = [r["articleId"] for r in articles]
    common = {"synthetic": True, "labelMethod": "synthetic_control", "labeler": "Deterministic test control"}
    cls_file = directory / "classification-labels.synthetic.jsonl"
    write_jsonl(cls_file, [{**common, "articleId": ids[0], "label": "economia", "geo": "panama", "stratum": "uniform"},
                          {**common, "articleId": ids[1], "label": "economia", "geo": "regional", "stratum": "uniform"}])
    pair_file = directory / "pairs-labels.synthetic.jsonl"
    write_jsonl(pair_file, [{**common, "snapshotId": sid, "a": ids[a], "b": ids[b], "sameEvent": gold,
                            "stratum": "synthetic_control"} for a, b, gold in [(0, 1, True), (0, 2, True), (0, 3, False), (1, 2, False)]])
    agenda_file = directory / "agenda-labels.synthetic.jsonl"
    write_jsonl(agenda_file, [{**common, "snapshotId": sid, "rulesVersion": "synthetic-scoring-v1",
                              "relevantTopicIds": ["synthetic_A"]}])
    ranking_file = directory / "agenda.synthetic.json"
    write_json(ranking_file, {"snapshotId": sid, "rulesVersion": "synthetic-scoring-v1",
                             "items": [{"id": "synthetic_A"}, {"id": "synthetic_B"}]})
    claims_file = directory / "claims-labels.synthetic.jsonl"
    write_jsonl(claims_file, [{**common, "snapshotId": sid, "type": "declaracion", "supported": True,
                              "citationCorrect": True, "citations": [{"evidenceId": ids[0], "field": "title"}]},
                             {**common, "snapshotId": sid, "type": "hecho", "supported": False,
                              "citationCorrect": False, "citations": [{"evidenceId": "inventado", "field": "title"}]}])
    commands = []

    def run(script, args, output):
        command = [sys.executable, str(ROOT / "eval" / script), *map(str, args), "--out", str(output)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40, check=False)
        commands.append({"command": command, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode:
            raise RuntimeError(json.dumps(commands[-1], ensure_ascii=False))
        return json.loads(output.read_text(encoding="utf-8"))

    cls = run("run_classification.py", ["--labels", cls_file, "--snapshot", f"laya_control={laya_control}",
              "--snapshot", f"baseline_control={baseline_control}"], directory / "classification.synthetic.json")
    assert cls["evaluationKind"] == "synthetic_control"
    result = cls["results"]["laya_control"]["all"]
    assert math.isclose(result["category"]["macroF1"], 2/3)
    assert result["category"]["accuracy"] == .5
    assert math.isclose(result["probabilityQuality"]["brier"], .65)
    assert math.isclose(result["probabilityQuality"]["ece"], .45)
    assert cls["results"]["baseline_control"]["all"]["category"]["accuracy"] == 1
    pairs = run("run_clustering_eval.py", ["--labels", pair_file, "--snapshot", f"control={laya_control}"], directory / "pairs.synthetic.json")
    assert pairs["evaluationKind"] == "synthetic_control"
    assert pairs["results"]["control"]["precision"] == .5
    assert pairs["results"]["control"]["recall"] == .5
    agenda = run("run_agenda_eval.py", ["--labels", agenda_file, "--ranking", ranking_file, "--snapshot", laya_control], directory / "agenda-result.synthetic.json")
    assert agenda["evaluationKind"] == "synthetic_control" and agenda["precisionAt5"] == .2
    claims = run("run_claims_eval.py", ["--labels", claims_file, "--snapshot", laya_control], directory / "claims-result.synthetic.json")
    assert claims["evaluationKind"] == "synthetic_control"
    assert claims["humanSupport"]["value"] == .5
    assert claims["factualCitationCoverageStructural"]["value"] == .5
    # Hash tampering must be rejected before a result can be produced.
    article_file = laya_control / "articles.jsonl"
    original = article_file.read_bytes()
    article_file.write_bytes(original + b"\n")
    try:
        command = [sys.executable, str(ROOT / "eval/run_classification.py"), "--labels", str(cls_file),
                   "--snapshot", f"tampered={laya_control}", "--out", str(directory / "must-not-exist.json")]
        negative = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
        assert negative.returncode != 0 and not (directory / "must-not-exist.json").exists()
        commands.append({"command": command, "exitCode": negative.returncode, "expectedFailure": "SHA-256 tamper rejected"})
    finally:
        article_file.write_bytes(original)
    assert verify_snapshot(laya_control)[0]
    return {"status": "passed", "evaluationKind": "synthetic_control", "command": " ".join(sys.argv),
            "ranAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "checks": ["classification CLI", "baseline comparison CLI", "raw Brier/ECE", "pair PR CLI", "agenda P@5 CLI",
                       "claim support/coverage CLI", "snapshot tamper rejection"],
            "commands": commands, "fixtureSnapshots": [laya_control.name, baseline_control.name],
            "evaluatorSha256": sha256_file(Path(__file__)),
            "note": "VALIDACIÓN DE HERRAMIENTAS con números analíticos sintéticos; no métricas humanas ni desempeño Laya."}


if __name__ == "__main__":
    output = ROOT / "eval/verification" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = verify(output)
    write_json(output / "receipt.json", report)
    print(f"7 comprobaciones de herramientas pasan, solo controles sintéticos -> {output / 'receipt.json'}")
