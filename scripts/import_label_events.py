#!/usr/bin/env python3
"""Valida una exportación de etiquetas y crea entradas de evaluación humana.

Los archivos generados se guardan en una carpeta derivada del hash de entrada;
no se modifican las hojas CSV ni los juicios previos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # ejecución como módulo o como script
    from .prepare_labeling import _canonical, _read_json, _read_jsonl, build_sheets, write_idempotent
except ImportError:  # pragma: no cover - usado al ejecutar python scripts/import_label_events.py
    from prepare_labeling import _canonical, _read_json, _read_jsonl, build_sheets, write_idempotent


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHEETS = ROOT / "apps" / "web" / "public" / "etiquetado" / "hojas.json"
DEFAULT_LABELS = ROOT / "eval" / "labels"
ROLES = {"editor", "producer", "reviewer", "juror"}
VALUES = {
    "topic": {"economia", "logistica_canal", "turismo", "servicios_publicos", "eventos_naturales", "regulacion", "indeterminado", "no_se"},
    "pair": {"si", "no", "no_se"},
    "claim": {"respaldada", "no_respaldada", "cita_incorrecta", "no_se"},
}


def _iso_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser una fecha ISO 8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} debe ser una fecha ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def _uuid(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} debe ser un UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} debe ser un UUID") from exc


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")


def _validated_sheet_ids(sheets_path: Path, snapshot_id: str, sheet_hash: str,
                         snapshot_dir: Path, labels_dir: Path) -> dict[str, set[str]]:
    sheets = _read_json(sheets_path)
    if sheets.get("version") != 1 or sheets.get("snapshotId") != snapshot_id or sheets.get("sheetHash") != sheet_hash:
        raise ValueError("La exportación no corresponde a las hojas y snapshot instalados")
    supplied_hash = sheets.get("sheetHash")
    payload = {key: value for key, value in sheets.items() if key != "sheetHash"}
    actual_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if supplied_hash != actual_hash:
        raise ValueError("La huella de las hojas instaladas no coincide")
    regenerated = build_sheets(snapshot_dir, labels_dir)
    if regenerated["sheetHash"] != supplied_hash:
        raise ValueError("Las hojas instaladas no corresponden al snapshot y muestras íntegros")
    ids: dict[str, set[str]] = {}
    for label_type, key in (("topic", "topics"), ("pair", "pairs"), ("claim", "claims")):
        entries = sheets.get(key)
        if not isinstance(entries, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in entries):
            raise ValueError(f"Las hojas instaladas tienen una lista {key} inválida")
        ids[label_type] = {row["id"] for row in entries}
        if len(ids[label_type]) != len(entries):
            raise ValueError(f"Las hojas instaladas repiten identificadores en {key}")
    return ids


def build_import(export_paths: Path | list[Path], snapshot_dir: Path, labels_dir: Path,
                 sheets_path: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    paths = [export_paths] if isinstance(export_paths, Path) else list(export_paths)
    if not paths:
        raise ValueError("Indica al menos una exportación de etiquetas")
    raw_exports = [path.read_bytes() for path in paths]
    input_hash = hashlib.sha256(b"\0".join(sorted(raw_exports))).hexdigest()
    manifest = _read_json(snapshot_dir / "manifest.json")
    snapshot_id = manifest.get("snapshotId")
    if not isinstance(snapshot_id, str):
        raise ValueError("El snapshot no declara un snapshotId válido")
    exports = [json.loads(raw) for raw in raw_exports]
    if any(not isinstance(export, dict) or export.get("version") != 1 for export in exports):
        raise ValueError("Todas las exportaciones deben usar version 1")
    if any(not isinstance(export.get("sheetHash"), str) for export in exports):
        raise ValueError("La exportación no incluye una huella de hojas válida")
    sheet_hashes = {export["sheetHash"] for export in exports}
    if len(sheet_hashes) != 1:
        raise ValueError("Las exportaciones pertenecen a huellas distintas; no se mezclan")
    sheet_hash = next(iter(sheet_hashes))
    if any(export.get("snapshotId") != snapshot_id for export in exports):
        raise ValueError("La exportación pertenece a otro snapshot")
    if not isinstance(sheet_hash, str) or len(sheet_hash) != 64 or any(ch not in "0123456789abcdef" for ch in sheet_hash):
        raise ValueError("La exportación no incluye una huella SHA-256 válida")
    valid_items = _validated_sheet_ids(sheets_path, snapshot_id, sheet_hash, snapshot_dir, labels_dir)
    incoming: list[Any] = []
    for export in exports:
        rows = export.get("labels")
        if not isinstance(rows, list):
            raise ValueError("Una exportación no contiene una lista de etiquetas")
        incoming.extend(rows)

    # Desduplicar solo eventos idénticos; un id repetido con datos diferentes se rechaza.
    by_id: dict[str, tuple[dict[str, Any], datetime]] = {}
    label_fields = {"id", "snapshotId", "sheetHash", "type", "itemId", "value", "comment", "role", "sessionId", "labeler", "labelMethod", "createdAt"}
    for index, label in enumerate(incoming):
        if not isinstance(label, dict):
            raise ValueError(f"La etiqueta {index + 1} no es un objeto")
        if set(label) != label_fields:
            raise ValueError(f"La etiqueta {index + 1} no cumple el esquema exacto de evento humano")
        event_id = _uuid(label.get("id"), f"labels[{index}].id")
        session_id = _uuid(label.get("sessionId"), f"labels[{index}].sessionId")
        label_type = label.get("type")
        item_id = label.get("itemId")
        if label_type not in VALUES or label.get("value") not in VALUES[label_type]:
            raise ValueError(f"La etiqueta {event_id} usa un tipo o valor no admitido")
        if not isinstance(item_id, str) or item_id not in valid_items[label_type]:
            raise ValueError(f"La etiqueta {event_id} no pertenece a las hojas instaladas")
        if label.get("snapshotId") != snapshot_id or label.get("sheetHash") != sheet_hash:
            raise ValueError(f"La etiqueta {event_id} tiene otra procedencia")
        if label.get("role") not in ROLES or label.get("labelMethod") != "human":
            raise ValueError(f"La etiqueta {event_id} no está firmada por un rol humano permitido")
        labeler, comment = label.get("labeler"), label.get("comment")
        if not isinstance(labeler, str) or len(labeler) > 120 or not isinstance(comment, str) or len(comment) > 2000:
            raise ValueError(f"La etiqueta {event_id} excede los límites de nombre o comentario")
        created = _iso_utc(label.get("createdAt"), f"labels[{index}].createdAt")
        normalized = {**label, "id": event_id, "sessionId": session_id}
        prior = by_id.get(event_id)
        if prior and prior[0] != normalized:
            raise ValueError(f"El UUID de evento {event_id} aparece con contenidos distintos")
        by_id[event_id] = (normalized, created)

    events = [entry[0] for entry in sorted(by_id.values(), key=lambda entry: (entry[1], entry[0]["id"]))]
    latest: dict[tuple[str, str], tuple[dict[str, Any], datetime]] = {}
    all_values: dict[tuple[str, str], set[str]] = {}
    for event, created in sorted(by_id.values(), key=lambda entry: (entry[1], entry[0]["id"])):
        key = (event["type"], event["itemId"])
        latest[key] = (event, created)
        all_values.setdefault(key, set()).add(event["value"])

    cls_samples = {row["id"]: row for row in _read_jsonl(labels_dir / f"cls_sample.{snapshot_id}.jsonl")}
    pair_samples = {row["id"]: row for row in _read_jsonl(labels_dir / f"pairs_sample.{snapshot_id}.jsonl")}
    claim_samples = {row["id"]: row for row in _read_jsonl(labels_dir / f"claims_review.{snapshot_id}.jsonl")}
    if not valid_items["topic"].issubset(cls_samples) or not valid_items["pair"].issubset(pair_samples) or not valid_items["claim"].issubset(claim_samples):
        raise ValueError("Las hojas instaladas y las muestras privadas no tienen los mismos ids")
    articles_hash = manifest.get("files", {}).get("articles.jsonl", {}).get("sha256")
    if not isinstance(articles_hash, str):
        raise ValueError("El manifest no incluye el hash de artículos")
    provenance = {"snapshotId": snapshot_id, "articlesSha256": articles_hash}

    cls_rows, pair_rows, claim_rows = [], [], []
    excluded_no_se = {"topic": 0, "pair": 0, "claim": 0}
    for item_id in sorted(valid_items["topic"]):
        chosen = latest.get(("topic", item_id))
        if not chosen:
            continue
        event = chosen[0]
        if event["value"] == "no_se":
            excluded_no_se["topic"] += 1
            continue
        sample = cls_samples[item_id]
        cls_rows.append({**provenance, "articleId": sample["articleId"], "label": event["value"], "geo": None,
                         "stratum": "uniform" if sample.get("stratum") == "uniforme" else sample.get("stratum"),
                         "labeler": event["labeler"], "role": event["role"], "sessionId": event["sessionId"],
                         "labelEventId": event["id"], "labelCreatedAt": event["createdAt"], "labelMethod": "human", "notes": event["comment"]})
    for item_id in sorted(valid_items["pair"]):
        chosen = latest.get(("pair", item_id))
        if not chosen:
            continue
        event = chosen[0]
        if event["value"] == "no_se":
            excluded_no_se["pair"] += 1
            continue
        sample = pair_samples[item_id]
        pair_rows.append({**provenance, "pairId": item_id, "a": sample["a"], "b": sample["b"], "stratum": sample["stratum"],
                          "sameEvent": event["value"] == "si", "labeler": event["labeler"], "role": event["role"],
                          "sessionId": event["sessionId"], "labelEventId": event["id"], "labelCreatedAt": event["createdAt"],
                          "labelMethod": "human", "notes": event["comment"]})
    for item_id in sorted(valid_items["claim"]):
        chosen = latest.get(("claim", item_id))
        if not chosen:
            continue
        event = chosen[0]
        if event["value"] == "no_se":
            excluded_no_se["claim"] += 1
            continue
        sample = claim_samples[item_id]
        judgment = event["value"]
        claim_rows.append({**sample, "supported": judgment == "respaldada", "citationCorrect": judgment != "cita_incorrecta",
                           "labeler": event["labeler"], "role": event["role"], "sessionId": event["sessionId"],
                           "labelEventId": event["id"], "labelCreatedAt": event["createdAt"], "labelMethod": "human",
                           "notes": event["comment"], "judgment": judgment})

    conflicts = sum(1 for values in all_values.values() if len(values) > 1)
    report = {
        "version": 1, "snapshotId": snapshot_id, "sheetHash": sheet_hash,
        "inputSha256": input_hash,
        "policy": "Se conserva el historial de eventos; para cada elemento se usa la etiqueta humana más reciente. Los no_se se conservan en el historial y se excluyen de las métricas.",
        "events": len(events), "itemsWithConflictingValues": conflicts,
        "latestByType": {
            label_type: sum(1 for kind, _item_id in latest if kind == label_type)
            for label_type in VALUES
        },
        "excludedNoSe": excluded_no_se,
        "metricRows": {"topic": len(cls_rows), "pair": len(pair_rows), "claim": len(claim_rows)},
    }
    files = {
        f"label_events.{snapshot_id}.jsonl": _jsonl_bytes(events),
        f"cls_labels.{snapshot_id}.jsonl": _jsonl_bytes(cls_rows),
        f"pairs_labels.{snapshot_id}.jsonl": _jsonl_bytes(pair_rows),
        f"claims_labels.{snapshot_id}.jsonl": _jsonl_bytes(claim_rows),
        "import-report.json": _json_bytes(report),
    }
    return files, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, action="append", required=True,
                        help="JSON descargado desde Etiquetar; repite la opción para combinar sesiones")
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data" / "snapshots" / "CURRENT")
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--sheets", type=Path, default=DEFAULT_SHEETS)
    parser.add_argument("--output-dir", type=Path, help="Carpeta destino; por defecto se deriva de snapshot y hash")
    args = parser.parse_args()
    files, report = build_import(args.export, args.snapshot, args.labels_dir, args.sheets)
    output_dir = args.output_dir or (DEFAULT_LABELS / "imported" / f"{report['snapshotId']}-{report['inputSha256'][:12]}")
    for name, content in files.items():
        write_idempotent(output_dir / name, content)
    print(f"snapshot={report['snapshotId']} eventos={report['events']} filas={report['metricRows']} salida={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
