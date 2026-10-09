"""Artefactos MiniLM precalculados, ligados por hash al corpus léxico original."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SemanticArtifacts:
    clusters: list[dict[str, Any]] = field(default_factory=list)
    neighbors: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    model: str | None = None
    warning: str | None = None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("una fila no es un objeto")
    return rows


def load_semantic_artifacts(root: Path, snapshot_path: Path, snapshot_id: str,
                            lexical_clusters: list[dict[str, Any]], article_ids: set[str]) -> SemanticArtifacts:
    """Activa ambos artefactos juntos o conserva íntegro el corpus léxico. Ninguna referencia se descarta en silencio."""
    folder = root / snapshot_id
    if not folder.resolve().is_relative_to(root.resolve()):
        return SemanticArtifacts(warning="Artefactos semánticos rechazados: identificador fuera de su raíz.")
    names = ("clusters.semantic.jsonl", "meta.json", "neighbors.semantic.jsonl", "meta.neighbors.json")
    if not folder.exists():
        return SemanticArtifacts()
    try:
        if any(not (folder / name).is_file() for name in names):
            raise ValueError("paquete incompleto")
        articles_sha, source_clusters_sha = _sha(snapshot_path / "articles.jsonl"), _sha(snapshot_path / "clusters.jsonl")
        metas = []
        for data_name, meta_name, hash_key in ((names[0], names[1], "clustersSha256"),
                                              (names[2], names[3], "neighborsSha256")):
            meta = json.loads((folder / meta_name).read_text(encoding="utf-8"))
            if (meta.get("schemaVersion") != 1 or meta.get("snapshotId") != snapshot_id
                    or meta.get("sourceArticlesSha256") != articles_sha
                    or meta.get("sourceClustersSha256") != source_clusters_sha
                    or meta.get(hash_key) != _sha(folder / data_name)):
                raise ValueError("schema, snapshot o SHA-256 no coincide")
            if not isinstance(meta.get("model"), str) or not meta["model"].strip():
                raise ValueError("modelo ausente")
            generated = datetime.fromisoformat(str(meta.get("generatedAt", "")).replace("Z", "+00:00"))
            offset = generated.utcoffset()
            if generated.tzinfo is None or offset is None or offset.total_seconds() != 0:
                raise ValueError("generatedAt debe ser UTC")
            metas.append(meta)
        if any(metas[0].get(key) != metas[1].get(key) for key in ("model", "modelRevision")):
            raise ValueError("modelos de agrupación y vecinos distintos")
        clusters = _rows(folder / names[0])
        ids = [row["clusterId"] for row in clusters]
        members = [aid for row in clusters for aid in row["memberArticleIds"]]
        if len(ids) != len(set(ids)) or set(members) != article_ids or len(members) != len(article_ids):
            raise ValueError("grupos duplicados o partición de artículos incompleta")
        lexical_members = {row["clusterId"]: set(row["memberArticleIds"]) for row in lexical_clusters}
        for row in clusters:
            own = set(row["memberArticleIds"])
            if row["representativeArticleId"] not in own or row.get("size") != len(own):
                raise ValueError("representante o tamaño de grupo inválido")
            if any(not group <= own for group in lexical_members.values() if own & group):
                raise ValueError("un grupo semántico divide un grupo léxico original")
            if any(aid not in article_ids for aid in row.get("contradictionCandidateIds", [])):
                raise ValueError("candidato a contradicción inexistente")
            if any(cid not in lexical_members for cid in row.get("mergedFromClusterIds", [])):
                raise ValueError("grupo original inexistente")
            for link in row.get("links", []):
                if link.get("a") not in own or link.get("b") not in own:
                    raise ValueError("arista fuera de su grupo")
        neighbors: dict[str, list[tuple[str, float]]] = {}
        for row in _rows(folder / names[2]):
            aid = row["articleId"]
            if aid not in article_ids or aid in neighbors:
                raise ValueError("artículo vecino desconocido o duplicado")
            parsed = []
            seen = set()
            for nid, value in row["neighbors"]:
                score = float(value)
                if nid not in article_ids or nid == aid or nid in seen or not math.isfinite(score) or not 0.6 <= score <= 1.000001:
                    raise ValueError("referencia o similitud de vecino inválida")
                parsed.append((nid, score))
                seen.add(nid)
            neighbors[aid] = sorted(parsed, key=lambda pair: (-pair[1], pair[0]))
        if set(neighbors) != article_ids:
            raise ValueError("cobertura de vecinos incompleta")
        return SemanticArtifacts(clusters=clusters, neighbors=neighbors, model=metas[0]["model"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        detail = "archivo ilegible" if isinstance(exc, OSError) else str(exc)
        return SemanticArtifacts(warning=f"Artefactos semánticos rechazados; se conserva el corpus léxico ({detail}).")
