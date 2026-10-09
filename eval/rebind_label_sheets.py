"""Reutiliza muestras humanas de evidencia idéntica con procedencia explícita, sin alterar juicios.

Las predicciones ocultas se actualizan al corte destino. No genera afirmaciones ni interpreta fuentes.
Falla antes de escribir si cambió el corpus, una cita, un tema de afirmación o ya existe una hoja destino.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from label_provenance import verified_manifest
from umbral_pipeline.util import iso_z, now_utc, read_jsonl, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def rebind_label_sheets(source: Path, target: Path, labels: Path) -> dict:
    original = verified_manifest(source)
    destination = verified_manifest(target)
    source_id, target_id = original["snapshotId"], destination["snapshotId"]
    if source_id == target_id:
        raise ValueError("Origen y destino deben ser snapshots diferentes")
    for filename in ("articles.jsonl", "indicators.jsonl"):
        if original["files"][filename]["sha256"] != destination["files"][filename]["sha256"]:
            raise ValueError(f"{filename} cambió: la muestra requiere una nueva revisión de evidencia")
    articles = {row["articleId"]: row for row in read_jsonl(target / "articles.jsonl")}
    indicators = {row["indicatorRowId"]: row for row in read_jsonl(target / "indicators.jsonl")}
    evidence = articles | indicators
    predictions = {row["articleId"]: row for row in read_jsonl(target / "predictions.jsonl")}
    clusters = {row["clusterId"]: row for row in read_jsonl(target / "clusters.jsonl")}
    cluster_of = {article_id: cluster_id for cluster_id, row in clusters.items() for article_id in row["memberArticleIds"]}
    sample_names = ("cls_sample", "pairs_sample", "claims_sample", "claims_review")
    csv_names = ("clasificacion", "pares", "afirmaciones")
    output_names = [f"{name}.{target_id}.jsonl" for name in sample_names]
    output_names += [f"{name}.{target_id}.csv" for name in csv_names]
    output_names.append(f"sheets.{target_id}.meta.json")
    if any((labels / name).exists() for name in output_names):
        raise ValueError("Ya existen hojas destino; no se sobrescriben posibles juicios humanos")
    samples = {}
    source_files = {}
    common = {"snapshotId": target_id, "sourceSnapshotId": source_id,
              "articlesSha256": destination["files"]["articles.jsonl"]["sha256"]}
    for name in sample_names:
        path = labels / f"{name}.{source_id}.jsonl"
        source_files[path.name] = sha256_file(path)
        rows = list(read_jsonl(path))
        for row in rows:
            row.update(common, sourceSampleSha256=source_files[path.name])
            if name == "cls_sample":
                article = articles[row["articleId"]]
                if article["title"] != row["title"]:
                    raise ValueError("El texto de una muestra de clasificación no coincide")
                prediction = predictions[row["articleId"]]
                row.update(predictedCategory=prediction["category"], predictedGeo=prediction["geoRelevance"])
            elif name == "pairs_sample":
                if articles[row["a"]]["title"] != row["titleA"] or articles[row["b"]]["title"] != row["titleB"]:
                    raise ValueError("El texto de una muestra de pares no coincide")
                row["predictedSameCluster"] = cluster_of[row["a"]] == cluster_of[row["b"]]
            else:
                if row["topicId"] not in clusters:
                    raise ValueError("Una afirmación ya no pertenece a un tema del snapshot")
                for citation in row.get("citations", []):
                    record = evidence.get(citation["evidenceId"])
                    field = citation.get("field")
                    if record is None or field not in record:
                        raise ValueError("La cita no existe en la evidencia actual")
                    if field == "title" and citation.get("passage") != record["title"]:
                        raise ValueError("El pasaje de la cita no coincide con el titular actual")
                    if citation["evidenceId"] in articles and citation["evidenceId"] not in clusters[row["topicId"]]["memberArticleIds"]:
                        raise ValueError("La cita ya no forma parte del tema original")
        samples[name] = rows
    csvs = {}
    for name in csv_names:
        path = labels / f"{name}.{source_id}.csv"
        source_files[path.name] = sha256_file(path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            rows = list(reader)
        sample_name = {"clasificacion": "cls_sample", "pares": "pairs_sample", "afirmaciones": "claims_review"}[name]
        sample_by_id = {row["id"]: row for row in samples[sample_name]}
        if sorted(row["id"] for row in rows) != sorted(sample_by_id):
            raise ValueError("El CSV no corresponde a los IDs de la muestra")
        for row in rows:
            sample = sample_by_id[row["id"]]
            if name == "clasificacion":
                row["predicción"] = sample["predictedCategory"]
            elif name == "pares":
                row["predicción"] = "mismo grupo" if sample["predictedSameCluster"] else "grupos distintos"
        csvs[name] = (fieldnames, rows)
    for name, rows in samples.items():
        with (labels / f"{name}.{target_id}.jsonl").open("x", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    for name, (fieldnames, rows) in csvs.items():
        with (labels / f"{name}.{target_id}.csv").open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(rows)
    receipt = {"schemaVersion": 1, **common, "generatedAt": iso_z(now_utc()),
               "method": "identical_evidence_rebind", "seed": "preservada de las muestras de origen",
               "indicatorsSha256": destination["files"]["indicators.jsonl"]["sha256"],
               "sourceFilesSha256": source_files, "counts": {name: len(rows) for name, rows in samples.items()},
               "judgments": "Juicios y comentarios originales preservados; predicciones ocultas del destino actualizadas.",
               "outputFilesSha256": {name: sha256_file(labels / name) for name in output_names[:-1]}}
    with (labels / output_names[-1]).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=ROOT / "eval/labels")
    args = parser.parse_args()
    receipt = rebind_label_sheets(args.source, args.target, args.labels)
    print(json.dumps({"snapshotId": receipt["snapshotId"], "counts": receipt["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
