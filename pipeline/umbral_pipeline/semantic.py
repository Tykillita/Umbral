"""Artefactos MiniLM multilingües sobre un snapshot verificado; el snapshot permanece inmutable.

Solo la generación importa sentence-transformers/PyTorch. La API lee JSONL precalculado.
Los titulares son datos de entrada, nunca instrucciones. La similitud no prueba mismo hecho ni verdad.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .cluster import UF, independent_provenance, norm_title, numbers_conflict, numbers_in, tokens
from .snapshot import verify_snapshot
from .util import iso_z, now_utc, parse_dt, read_jsonl, sha256_file, sha256_hex, write_json, write_jsonl

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_SNAPSHOT_ID = re.compile(r"\d{8}-[a-f0-9]{8}")
_PANAMA = re.compile(r"\b(rep[uú]blica de )?panam[aá]\b|\bpaname[ñn]\w*\b|\bpanamanian\b", re.I)
_GENERIC = set(
    "panama panameno panamena panamenos panamanian colombia mexico guatemala costa rica dominicana "
    "venezuela ecuador nuevo nueva new hoy today dia day ano year anos years".split()
)
_ENTITY_STOP = _GENERIC | set(
    "gobierno presidente ministro comercio canal diario hoy nación noticias prensa latina mundial juegos "
    "liga copa selección asamblea tribunal fiscalía director purchases shares stock company economía producto "
    "proyecto reforma consejo segundo nuevas nuevo turismo localizan gremios empresas policia grupos".split()
)
_ENTITY_STOP = {norm_title(word) for word in _ENTITY_STOP}
# Grupos de acciones comparables ES/EN; por debajo del umbral alto compartir sustantivos no basta.
_ACTION_PREFIXES = {
    "increase": ("aument", "increment", "crec", "increas", "raise", "expand", "ampli"),
    "decrease": ("dismin", "reduci", "reduc", "decreas", "declin", "recorta"),
    "approval": ("aprueb", "aproba", "approv", "autoriza", "accept"),
    "rejection": ("rechaz", "reject", "niega", "denies", "cancela"),
    "opening": ("inaugur", "apertura", "comenz", "comien", "arranc", "opening", "opens", "begins"),
    "closing": ("clausur", "cerraron", "cierre", "finaliza", "concluy", "closing", "closes"),
    "detention": ("detien", "deten", "detenc", "arrest"),
    "recovery": ("localiz", "recuper", "encuentr", "recover", "found"),
    "travel": ("visit", "viaj", "travel", "vuel", "flight"),
    "agreement": ("acuerd", "firma", "contrato", "sign", "agreement", "contract"),
    "advance": ("avanza", "avancen", "advance"),
    "defeat": ("perdio", "perdieron", "pierde", "perder", "derrota", "defeat", "lost", "loss"),
    "award": ("condecor", "medalla", "honor", "merito", "award"),
    "farewell": ("desped", "despid", "adios", "funebr", "farewell", "homenaje"),
    "response": ("respond", "reaccion", "reaction"),
    "declaration": ("afirma", "asegura", "declara", "expresa", "said", "says", "claims"),
    "protest": ("protest", "manifest"),
}
_OPPOSITE_ACTIONS = (("increase", "decrease"), ("approval", "rejection"), ("opening", "closing"))
_MODEL_FILES = [
    "modules.json", "config*.json", "sentence_bert_config.json", "tokenizer*", "special_tokens_map.json",
    "vocab.txt", "sentencepiece.bpe.model", "model.safetensors", "1_Pooling/config.json",
]


@dataclass(frozen=True)
class SemanticParameters:
    threshold: float = 0.74
    high_threshold: float = 0.84
    lexical_anchors: int = 2
    window_hours: float = 72
    neighbor_k: int = 8
    neighbor_threshold: float = 0.6

    def validate(self) -> None:
        if not 0 <= self.threshold <= self.high_threshold <= 1:
            raise ValueError("Los umbrales de agrupación deben cumplir 0 ≤ threshold ≤ high_threshold ≤ 1")
        if self.lexical_anchors < 1 or not math.isfinite(self.window_hours) or self.window_hours <= 0:
            raise ValueError("El anclaje debe ser positivo y la ventana debe ser finita y positiva")
        if self.neighbor_k < 1 or not 0 <= self.neighbor_threshold <= 1:
            raise ValueError("k debe ser positivo y el umbral de vecinos debe estar entre 0 y 1")


DEFAULT_PARAMETERS = SemanticParameters()


def embedding_text(title: str) -> str:
    """Retira el país omnipresente del cálculo; conserva siempre el titular original en el snapshot."""
    return re.sub(r"\s+", " ", _PANAMA.sub(" ", title)).strip()


def content_anchors(title: str) -> set[str]:
    return {word[:5] for word in tokens(title) if word not in _GENERIC and not word.isdigit() and len(word) > 3}


def event_actions(title: str) -> set[str]:
    words = tokens(title)
    return {action for action, prefixes in _ACTION_PREFIXES.items() if any(word.startswith(prefixes) for word in words)}


def named_anchors(title: str) -> set[str]:
    """Guardia conservadora para nombres capitalizados; no presume que títulos completos en mayúsculas sean entidades."""
    words = re.findall(r"[^\W\d_]+", embedding_text(title), flags=re.UNICODE)
    if words and sum(word[0].isupper() for word in words) / len(words) > .7:
        return set()
    return {norm_title(word) for word in words if len(word) > 3 and word[0].isupper()
            and norm_title(word) not in _ENTITY_STOP}


def short_latin_headline(title: str) -> bool:
    text = embedding_text(title)
    letters = re.findall(r"[^\W\d_]", text, flags=re.UNICODE)
    latin = re.findall(r"[a-zA-Z]", text)
    return bool(letters) and len(latin) / len(letters) > .7 and len(tokens(text)) < 4


def _event_time(article: dict[str, Any]):
    return next((date for field in ("publishedAt", "effectiveDate", "detectedAt")
                 if (date := parse_dt(article.get(field))) is not None), None)


def _validate_matrix(articles: list[dict[str, Any]], similarities: np.ndarray) -> None:
    if similarities.shape != (len(articles), len(articles)) or not np.isfinite(similarities).all():
        raise ValueError("La matriz semántica no es finita o no corresponde a los artículos")
    if not np.allclose(similarities, similarities.T, atol=1e-5):
        raise ValueError("La matriz de similitud debe ser simétrica")
    if np.any(similarities < -1.00001) or np.any(similarities > 1.00001):
        raise ValueError("La similitud coseno debe estar entre -1 y 1")


def semantic_neighbors(
    articles: list[dict[str, Any]], similarities: np.ndarray, *, k: int = 8, threshold: float = 0.6,
) -> list[dict[str, Any]]:
    """Vecinos sirven para recuperar evidencia relacionada, incluso cifras discrepantes y fechas distintas."""
    _validate_matrix(articles, similarities)
    if k < 1 or not 0 <= threshold <= 1:
        raise ValueError("Parámetros de vecinos no válidos")
    ids = [a["articleId"] for a in articles]
    rows = []
    for i, article_id in enumerate(ids):
        order = sorted((j for j in range(len(ids)) if j != i), key=lambda j: (-float(similarities[i, j]), ids[j]))
        neighbors = [[ids[j], round(float(np.clip(similarities[i, j], -1, 1)), 6)]
                     for j in order[:k] if similarities[i, j] >= threshold]
        rows.append({"articleId": article_id, "neighbors": neighbors})
    return rows


def semantic_clusters(
    articles: list[dict[str, Any]], clusters: list[dict[str, Any]], similarities: np.ndarray,
    parameters: SemanticParameters = DEFAULT_PARAMETERS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Une clusters base con testigos de mismo hecho y sin encadenar A≈B≈C cuando A≉C.

    Cada pareja de clusters base de un grupo nuevo debe tener un testigo elegible. Además, todas
    las fechas del grupo deben caber en la ventana y ninguna pareja puede tener cifras dispares.
    Esas parejas quedan como candidatos trazables entre grupos y siguen presentes en los vecinos.
    """
    parameters.validate()
    _validate_matrix(articles, similarities)
    by_id = {a["articleId"]: a for a in articles}
    covered = [article_id for cluster in clusters for article_id in cluster["memberArticleIds"]]
    if len(by_id) != len(articles) or sorted(covered) != sorted(by_id):
        raise ValueError("Los clusters base deben particionar los artículos sin duplicados")
    cluster_ids = [c["clusterId"] for c in clusters]
    if len(set(cluster_ids)) != len(clusters):
        raise ValueError("clusterId base duplicado")
    cluster_of = {a: c["clusterId"] for c in clusters for a in c["memberArticleIds"]}
    base_by_id = {c["clusterId"]: c for c in clusters}
    ids = [a["articleId"] for a in articles]
    times = {a["articleId"]: _event_time(a) for a in articles}
    anchors = [content_anchors(a["title"]) for a in articles]
    actions = [event_actions(a["title"]) for a in articles]
    names = [named_anchors(a["title"]) for a in articles]
    numbers = {a["articleId"]: numbers_in(a["title"]) for a in articles}
    candidate_links: dict[tuple[str, str], dict[str, Any]] = {}
    contradictory: dict[str, set[str]] = defaultdict(set)
    rejected: Counter[str] = Counter()
    for i, article_id in enumerate(ids):
        for j in range(i + 1, len(ids)):
            other_id = ids[j]
            if cluster_of[article_id] == cluster_of[other_id]:
                continue
            score = float(similarities[i, j])
            if score < parameters.threshold:
                continue
            # Un nombre/país común no identifica el partido, la empresa ni el caso concreto.
            same_language = by_id[article_id].get("language") == by_id[other_id].get("language")
            if same_language and names[i] - names[j] and names[j] - names[i]:
                rejected["differentNamedActors"] += 1
                continue
            if any(first in actions[i] and second in actions[j] or second in actions[i] and first in actions[j]
                   for first, second in _OPPOSITE_ACTIONS):
                rejected["oppositeActions"] += 1
                continue
            if short_latin_headline(by_id[article_id]["title"]) or short_latin_headline(by_id[other_id]["title"]):
                rejected["shortHeadlines"] += 1
                continue
            if score < parameters.high_threshold and len(anchors[i] & anchors[j]) < parameters.lexical_anchors:
                rejected["lexicalAnchors"] += 1
                continue
            if score < parameters.high_threshold and not actions[i] & actions[j]:
                rejected["differentEventActions"] += 1
                continue
            first, second = times[article_id], times[other_id]
            if first is None or second is None or abs((first - second).total_seconds()) > parameters.window_hours * 3600:
                rejected["timeWindow"] += 1
                continue
            if numbers_conflict(numbers[article_id], numbers[other_id]):
                contradictory[article_id].add(other_id)
                contradictory[other_id].add(article_id)
                rejected["conflictingNumbers"] += 1
                continue
            pair = tuple(sorted((cluster_of[article_id], cluster_of[other_id])))
            link = {"a": article_id, "b": other_id, "method": "semantic_embedding",
                    "score": round(min(1.0, score), 6)}
            old = candidate_links.get(pair)
            if old is None or (link["score"], link["a"], link["b"]) > (old["score"], old["a"], old["b"]):
                candidate_links[pair] = link

    uf = UF(cluster_ids)
    components = {cluster_id: {cluster_id} for cluster_id in cluster_ids}
    links = []
    for (first_id, second_id), link in sorted(candidate_links.items(), key=lambda item: (-item[1]["score"], item[0])):
        first_root, second_root = uf.find(first_id), uf.find(second_id)
        if first_root == second_root:
            continue
        first_parts, second_parts = components[first_root], components[second_root]
        if not all(tuple(sorted((a, b))) in candidate_links for a in first_parts for b in second_parts):
            rejected["transitiveChain"] += 1
            continue
        first_members = [a for c in first_parts for a in base_by_id[c]["memberArticleIds"]]
        second_members = [a for c in second_parts for a in base_by_id[c]["memberArticleIds"]]
        all_times = [times[a] for a in first_members + second_members]
        if any(t is None for t in all_times) or (max(all_times) - min(all_times)).total_seconds() > parameters.window_hours * 3600:
            rejected["componentTimeWindow"] += 1
            continue
        if any(numbers_conflict(numbers[a], numbers[b]) for a in first_members for b in second_members):
            rejected["componentConflictingNumbers"] += 1
            continue
        uf.union(first_root, second_root)
        combined_parts = first_parts | second_parts
        components.pop(first_root)
        components.pop(second_root)
        components[uf.find(first_root)] = combined_parts
        links.append(link)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        grouped[uf.find(cluster["clusterId"])].append(cluster)
    output = []
    for parts in grouped.values():
        members = sorted({a for c in parts for a in c["memberArticleIds"]}, key=lambda a: (by_id[a].get("effectiveDate") or "", a))
        member_set = set(members)
        peer_ids = sorted(({a for c in parts for a in c.get("contradictionCandidateIds", [])}
                           | {peer for a in members for peer in contradictory[a]}) - member_set)
        result = dict(parts[0])
        if len(parts) > 1:
            selected = [by_id[a] for a in members]
            known = [a for a in selected if a.get("publishedAt")]
            candidates = [a for a in known if a.get("language") == "es"] or known or selected
            representative = min(candidates, key=lambda a: (a.get("publishedAt") or "~", a["articleId"]))
            publications = sorted(a["publishedAt"] for a in selected if a.get("publishedAt"))
            votes: Counter[str] = Counter()
            for cluster in parts:
                if cluster.get("category") and cluster["category"] != "indeterminado":
                    votes[cluster["category"]] += cluster["size"]
            recirculation = next((c for c in parts if c.get("isRecirculation")), None)
            result.update({
                "clusterId": "evt_" + sha256_hex("|".join(sorted(members)))[:16],
                "memberArticleIds": members, "size": len(members),
                "representativeArticleId": representative["articleId"],
                "category": max(votes, key=lambda category: (votes[category], category)) if votes else "indeterminado",
                "provenanceKeys": sorted({a["provenance"]["key"] for a in selected}),
                "independentProvenanceCount": independent_provenance(selected, {a["articleId"]: norm_title(a["title"]) for a in selected}),
                "outletCount": len({a["domain"] for a in selected}),
                "links": [link for c in parts for link in c.get("links", [])]
                         + [link for link in links if link["a"] in member_set and link["b"] in member_set],
                "ambiguous": any(c.get("ambiguous") for c in parts),
                "ambiguousCandidateIds": sorted({a for c in parts for a in c.get("ambiguousCandidateIds", [])} - member_set),
                "firstPublishedAt": publications[0] if publications else None,
                "lastPublishedAt": publications[-1] if publications else None,
                "originalPublishedAt": publications[0] if publications else None,
                "isRecirculation": recirculation is not None,
                "recirculationReason": recirculation.get("recirculationReason") if recirculation else None,
                "dataOrigin": "fixture" if all(a.get("dataOrigin") == "fixture" for a in selected) else "real",
                "provisional": any(c.get("provisional") for c in parts),
                "mergedFromClusterIds": sorted(c["clusterId"] for c in parts),
            })
        result.update({"hasContradictionCandidate": bool(peer_ids or any(c.get("hasContradictionCandidate") for c in parts)),
                       "contradictionCandidateIds": peer_ids})
        output.append(result)
    output.sort(key=lambda c: (c["memberArticleIds"][0], c["clusterId"]))
    return output, {"articles": len(articles), "clustersBefore": len(clusters), "clustersAfter": len(output),
                    "semanticLinks": len(links), "contradictionPairs": sum(len(peers) for peers in contradictory.values()) // 2,
                    "rejectedCandidates": dict(sorted(rejected.items()))}


def resolve_snapshot(data_dir: Path, snapshot_id: str | None = None) -> Path:
    snapshot_id = snapshot_id or (data_dir / "snapshots" / "CURRENT").read_text(encoding="utf-8").strip()
    if _SNAPSHOT_ID.fullmatch(snapshot_id) is None:
        raise ValueError("snapshotId no válido")
    snapshot = data_dir / "snapshots" / snapshot_id
    ok, problems = verify_snapshot(snapshot)
    if not ok:
        raise ValueError("Snapshot no válido: " + "; ".join(problems))
    return snapshot


def encode_titles(articles: list[dict[str, Any]], *, revision: str | None = None, offline: bool = False,
                  batch_size: int = 64) -> tuple[np.ndarray, dict[str, Any]]:
    """Descarga solo archivos necesarios del modelo oficial y fija la revisión resuelta para el recibo."""
    try:
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Instala el extra local: uv sync --project pipeline --extra semantic") from exc
    if batch_size < 1:
        raise ValueError("batch_size debe ser positivo")
    model_path = Path(snapshot_download(DEFAULT_MODEL, revision=revision, allow_patterns=_MODEL_FILES,
                                        local_files_only=offline))
    model = SentenceTransformer(str(model_path), device="cpu", local_files_only=True, trust_remote_code=False)
    vectors = np.asarray(model.encode([embedding_text(a["title"]) for a in articles], batch_size=batch_size,
                                     normalize_embeddings=True, show_progress_bar=False), dtype=np.float32)
    if not len(articles):
        vectors = np.empty((0, 384), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(articles) or not np.isfinite(vectors).all():
        raise ValueError("El modelo devolvió embeddings inválidos")
    model_files = [{"path": path.relative_to(model_path).as_posix(), "bytes": path.stat().st_size,
                    "sha256": sha256_file(path)} for path in sorted(model_path.rglob("*")) if path.is_file()]
    return vectors, {"model": DEFAULT_MODEL, "modelRevision": model_path.name,
                     "modelSizeBytes": sum(file["bytes"] for file in model_files), "modelFiles": model_files,
                     "embeddingDimensions": vectors.shape[1], "device": "cpu"}


def write_semantic_artifacts(
    data_dir: Path, snapshot: Path, articles: list[dict[str, Any]], clusters: list[dict[str, Any]],
    neighbors: list[dict[str, Any]], model_info: dict[str, Any], counts: dict[str, Any],
    parameters: SemanticParameters = DEFAULT_PARAMETERS,
) -> Path:
    """Metadata se reemplaza al final; cualquier mezcla temporal de archivos cae por hash en el lector."""
    destination = data_dir / "agrupacion" / snapshot.name
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / (".building-" + uuid.uuid4().hex)
    temporary.mkdir()
    common = {"schemaVersion": 1, "snapshotId": snapshot.name, "generatedAt": iso_z(now_utc()),
              **model_info, "sourceArticlesSha256": sha256_file(snapshot / "articles.jsonl"),
              "sourceClustersSha256": sha256_file(snapshot / "clusters.jsonl"),
              "text": "titular sin la entidad Panamá; el original permanece en articles.jsonl"}
    try:
        write_jsonl(temporary / "clusters.semantic.jsonl", clusters)
        write_jsonl(temporary / "neighbors.semantic.jsonl", neighbors)
        write_json(temporary / "meta.json", {
            **common, "method": "semantic_embedding", "threshold": parameters.threshold,
            "highThreshold": parameters.high_threshold, "lexicalAnchor": parameters.lexical_anchors,
            "windowHours": parameters.window_hours, "clustersSha256": sha256_file(temporary / "clusters.semantic.jsonl"),
            "counts": counts, "guards": ["base_cluster_complete_linkage", "component_time_window", "conflicting_numbers_keep_separate",
                                         "named_actor_compatibility", "shared_action_below_high_threshold", "opposite_action_rejection", "short_headline_rejection"],
            "limits": "Heurística de titulares; misma temática no acredita mismo hecho. Requiere evaluación con pares humanos.",
        })
        write_json(temporary / "meta.neighbors.json", {
            **common, "k": parameters.neighbor_k, "threshold": parameters.neighbor_threshold,
            "neighborsSha256": sha256_file(temporary / "neighbors.semantic.jsonl"),
            "articles": len(articles), "withNeighbors": sum(bool(row["neighbors"]) for row in neighbors),
            "fusion": "reciprocal rank fusion (k=60); el consumidor conserva citas y abstenciones",
        })
        ok, problems = verify_semantic_artifacts(snapshot, temporary)
        if not ok:
            raise ValueError("Artefactos inválidos: " + "; ".join(problems))
        for name in ("clusters.semantic.jsonl", "neighbors.semantic.jsonl", "meta.json", "meta.neighbors.json"):
            (temporary / name).replace(destination / name)
    finally:
        for path in temporary.iterdir():
            path.unlink()
        temporary.rmdir()
    return destination


def verify_semantic_artifacts(snapshot: Path, directory: Path) -> tuple[bool, list[str]]:
    """Comprueba origen, hashes, cobertura exacta y referencias; no importa ni descarga modelos."""
    problems = []
    try:
        ok, source_problems = verify_snapshot(snapshot)
        if not ok:
            return False, source_problems
        articles = list(read_jsonl(snapshot / "articles.jsonl"))
        ids = {article["articleId"] for article in articles}
        base_clusters = list(read_jsonl(snapshot / "clusters.jsonl"))
        base_ids = {cluster["clusterId"] for cluster in base_clusters}
        for metadata_name, content_name, hash_key in (
            ("meta.json", "clusters.semantic.jsonl", "clustersSha256"),
            ("meta.neighbors.json", "neighbors.semantic.jsonl", "neighborsSha256"),
        ):
            metadata = json.loads((directory / metadata_name).read_text(encoding="utf-8"))
            if metadata.get("schemaVersion") != 1 or metadata.get("snapshotId") != snapshot.name:
                problems.append(f"{metadata_name}: schemaVersion o snapshotId distinto")
            if metadata.get("sourceArticlesSha256") != sha256_file(snapshot / "articles.jsonl"):
                problems.append(f"{metadata_name}: sourceArticlesSha256 distinto")
            if metadata.get("sourceClustersSha256") != sha256_file(snapshot / "clusters.jsonl"):
                problems.append(f"{metadata_name}: sourceClustersSha256 distinto")
            if metadata.get(hash_key) != sha256_file(directory / content_name):
                problems.append(f"{metadata_name}: {hash_key} distinto")
        clusters = list(read_jsonl(directory / "clusters.semantic.jsonl"))
        if sorted(a for cluster in clusters for a in cluster["memberArticleIds"]) != sorted(ids):
            problems.append("clusters semánticos no particionan los artículos")
        if len({cluster["clusterId"] for cluster in clusters}) != len(clusters):
            problems.append("clusterId semántico duplicado")
        for cluster in clusters:
            members = set(cluster["memberArticleIds"])
            if cluster["size"] != len(members) or cluster["representativeArticleId"] not in members:
                problems.append("tamaño o representante semántico inválido")
            if set(cluster.get("mergedFromClusterIds", [])) - base_ids:
                problems.append("mergedFromClusterIds desconocidos")
            for key in ("ambiguousCandidateIds", "contradictionCandidateIds"):
                if set(cluster.get(key, [])) - (ids - members):
                    problems.append(f"{key} inválidos")
            if any(link["a"] not in members or link["b"] not in members for link in cluster["links"]):
                problems.append("enlace semántico fuera de su grupo")
        neighbors = list(read_jsonl(directory / "neighbors.semantic.jsonl"))
        neighbor_meta = json.loads((directory / "meta.neighbors.json").read_text(encoding="utf-8"))
        if sorted(row["articleId"] for row in neighbors) != sorted(ids):
            problems.append("vecinos no cubren exactamente los artículos")
        for row in neighbors:
            peers = row["neighbors"]
            if len(peers) > neighbor_meta["k"] or len({peer[0] for peer in peers}) != len(peers):
                problems.append("vecinos duplicados o mayores que k")
            if any(peer_id not in ids or peer_id == row["articleId"] or not math.isfinite(score)
                   or not neighbor_meta["threshold"] <= score <= 1 for peer_id, score in peers):
                problems.append("referencia o similitud de vecino inválida")
            if any(a[1] < b[1] for a, b in zip(peers, peers[1:], strict=False)):
                problems.append("vecinos fuera de orden")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems.append(f"No se pudieron verificar artefactos: {exc}")
    return not problems, problems


def run_semantic(data_dir: Path, *, snapshot_id: str | None = None, revision: str | None = None,
                 offline: bool = False, parameters: SemanticParameters = DEFAULT_PARAMETERS,
                 batch_size: int = 64) -> Path:
    parameters.validate()
    snapshot = resolve_snapshot(data_dir, snapshot_id)
    articles = list(read_jsonl(snapshot / "articles.jsonl"))
    base_clusters = list(read_jsonl(snapshot / "clusters.jsonl"))
    source_hashes = (sha256_file(snapshot / "articles.jsonl"), sha256_file(snapshot / "clusters.jsonl"))
    vectors, model_info = encode_titles(articles, revision=revision, offline=offline, batch_size=batch_size)
    similarities = np.clip(vectors @ vectors.T, -1, 1)
    clusters, counts = semantic_clusters(articles, base_clusters, similarities, parameters)
    neighbors = semantic_neighbors(articles, similarities, k=parameters.neighbor_k, threshold=parameters.neighbor_threshold)
    if source_hashes != (sha256_file(snapshot / "articles.jsonl"), sha256_file(snapshot / "clusters.jsonl")):
        raise ValueError("El snapshot cambió durante la generación")
    return write_semantic_artifacts(data_dir, snapshot, articles, clusters, neighbors, model_info, counts, parameters)
