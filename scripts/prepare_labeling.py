#!/usr/bin/env python3
"""Prepara las hojas ciegas que consume la vista Etiquetar.

La salida se construye con una lista permitida de campos de evidencia. No copia
predicciones, etiquetas previas ni metadatos de evaluación desde las muestras.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data" / "snapshots" / "CURRENT"
DEFAULT_LABELS = ROOT / "eval" / "labels"
DEFAULT_OUTPUT = ROOT / "apps" / "web" / "public" / "etiquetado" / "hojas.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: se esperaba un objeto JSON")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{number}: se esperaba un objeto JSON")
        rows.append(row)
    return rows


def _canonical(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _canonical(value[key])
            for key in sorted(value)
        ) + "}"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def build_sheets(snapshot_dir: Path, labels_dir: Path) -> dict[str, Any]:
    manifest = _read_json(snapshot_dir / "manifest.json")
    snapshot_id = manifest.get("snapshotId")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ValueError("El manifest no declara un snapshotId válido")
    article_entry = manifest.get("files", {}).get("articles.jsonl", {})
    expected_articles_hash = article_entry.get("sha256")
    articles_path = snapshot_dir / "articles.jsonl"
    actual_articles_hash = _sha256(articles_path.read_bytes())
    if actual_articles_hash != expected_articles_hash:
        raise ValueError("El SHA-256 de articles.jsonl no coincide con el manifest")

    metadata_path = labels_dir / f"sheets.{snapshot_id}.meta.json"
    metadata = _read_json(metadata_path)
    if metadata.get("snapshotId") != snapshot_id or metadata.get("articlesSha256") != actual_articles_hash:
        raise ValueError("La muestra de etiquetado pertenece a otro snapshot o corpus")
    if metadata.get("method") != "identical_evidence_rebind":
        raise ValueError("La muestra no tiene un rebind de evidencia documentado")

    file_names = {
        "topics": f"cls_sample.{snapshot_id}.jsonl",
        "pairs": f"pairs_sample.{snapshot_id}.jsonl",
        "claims": f"claims_review.{snapshot_id}.jsonl",
    }
    for name in file_names.values():
        expected = metadata.get("outputFilesSha256", {}).get(name)
        if not expected or _sha256((labels_dir / name).read_bytes()) != expected:
            raise ValueError(f"La muestra {name} no coincide con el recibo de rebind")

    articles = {
        row["articleId"]: row
        for row in _read_jsonl(articles_path)
        if row.get("dataOrigin") == "real" and isinstance(row.get("articleId"), str)
    }

    def source(article_id: Any, *, text: str | None = None) -> dict[str, Any]:
        if not isinstance(article_id, str) or article_id not in articles:
            raise ValueError(f"La muestra referencia una noticia ausente: {article_id!r}")
        article = articles[article_id]
        result = {
            "id": article_id,
            "text": text if text is not None else article.get("title", ""),
            "outlet": article.get("outlet") or article.get("domain") or "Fuente sin nombre",
            "url": article.get("url") or article.get("canonicalUrl") or "",
            "publishedAt": _optional_text(article.get("publishedAt")),
            "detectedAt": _optional_text(article.get("detectedAt")),
        }
        if not all(isinstance(result[key], str) for key in ("text", "outlet", "url")):
            raise ValueError(f"Metadatos de fuente inválidos para {article_id}")
        return result

    topics = [source(row.get("articleId"), text=row.get("title")) for row in _read_jsonl(labels_dir / file_names["topics"])]

    pairs = []
    for row in _read_jsonl(labels_dir / file_names["pairs"]):
        pair_id = row.get("id")
        if not isinstance(pair_id, str) or not pair_id:
            raise ValueError("La muestra contiene un par sin id")
        pairs.append({"id": pair_id, "a": source(row.get("a")), "b": source(row.get("b"))})

    claims = []
    for row in _read_jsonl(labels_dir / file_names["claims"]):
        claim_id, text, citations = row.get("id"), row.get("text"), row.get("citations")
        if not isinstance(claim_id, str) or not claim_id or not isinstance(text, str) or not isinstance(citations, list):
            raise ValueError("La muestra contiene una afirmación inválida")
        safe_citations = []
        for citation in citations:
            if not isinstance(citation, dict):
                raise ValueError(f"Cita inválida en {claim_id}")
            evidence_id = citation.get("evidenceId")
            cited_source = source(evidence_id)
            field = citation.get("field")
            if not isinstance(field, str) or not field:
                raise ValueError(f"La cita de {claim_id} no declara el campo evaluado")
            safe_citations.append({
                "evidenceId": evidence_id,
                "field": field,
                "passage": _optional_text(citation.get("passage")),
                "title": cited_source["text"],
                "outlet": cited_source["outlet"],
                "url": cited_source["url"],
                "publishedAt": cited_source["publishedAt"],
                "detectedAt": cited_source["detectedAt"],
            })
        claims.append({"id": claim_id, "text": text, "citations": safe_citations})

    payload = {"version": 1, "snapshotId": snapshot_id, "topics": topics, "pairs": pairs, "claims": claims}
    payload["sheetHash"] = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return payload


def write_idempotent(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return
        raise FileExistsError(f"{path} ya existe con otro contenido; no se sobrescribe")
    with path.open("xb") as target:
        target.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    sheets = build_sheets(args.snapshot, args.labels_dir)
    content = (json.dumps(sheets, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_idempotent(args.output, content)
    print(f"snapshot={sheets['snapshotId']} hash={sheets['sheetHash']} topics={len(sheets['topics'])} pairs={len(sheets['pairs'])} claims={len(sheets['claims'])} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
