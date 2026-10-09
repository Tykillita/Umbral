"""Carga del snapshot (contrato `docs/contracts/snapshot-schema.md` v1.0.0) y verificación de integridad."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings, repo_root
from .models import (
    Category,
    DataMode,
    EvidenceArticle,
    GeoRelevance,
    IndicatorPoint,
    IntegrityReport,
)
from .security import looks_like_instruction
from .seismology import SeismicEvent, load_seismic_events
from .semantic import load_semantic_artifacts

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "snapshot-fixture"

SPONSORED_RE = re.compile(r"/(publirreportajes?|publireportajes?|patrocinad[oa]s?|sponsored|branded-?content)(/|$|\?|-)", re.IGNORECASE)
_CATEGORIES = {c.value for c in Category}
_GEO = {g.value for g in GeoRelevance}


def parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_input_text(title: str) -> str:
    """Normalización del texto de entrada de Laya (contrato: titular, NFC, espacios colapsados)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", title)).strip()


def prediction_input_hash(title: str) -> str:
    return hashlib.sha256(normalize_input_text(title).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@dataclass
class Corpus:
    path: Path
    snapshot_id: str
    data_mode: DataMode
    provisional: bool
    contains_fixtures: bool
    classifier: str | None
    cutoff: datetime
    manifest: dict[str, Any]
    quality_report: dict[str, Any] | None
    metrics: dict[str, Any] | None
    sources: list[dict[str, Any]]
    articles: dict[str, EvidenceArticle]
    indicators: dict[str, IndicatorPoint]
    clusters: dict[str, dict[str, Any]]
    integrity: IntegrityReport
    notes: list[str] = field(default_factory=list)
    neighbors: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    semantic_model: str | None = None
    events: dict[str, SeismicEvent] = field(default_factory=dict)
    events_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "articles": len(self.articles),
            "indicators": len(self.indicators),
            "indicatorValues": sum(1 for i in self.indicators.values() if not i.is_missing),
            "clusters": len(self.clusters),
        }


def _verify_integrity(path: Path, manifest: dict[str, Any], articles_raw: list[dict], preds_raw: list[dict]) -> IntegrityReport:
    errors: list[str] = []
    checked = 0
    files = manifest.get("files") or {}
    for name, meta in files.items():
        fp = path / name
        if not fp.resolve().is_relative_to(path.resolve()):
            errors.append(f"archivo del manifest fuera del snapshot: {name}")
            continue
        expected = (meta or {}).get("sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            errors.append(f"SHA-256 ausente o inválido: {name}")
            continue
        if not fp.exists():
            errors.append(f"archivo del manifest ausente: {name}")
            continue
        checked += 1
        if expected and sha256_file(fp) != expected:
            errors.append(f"SHA-256 no coincide: {name}")
    if not files:
        errors.append("manifest sin inventario de archivos (files)")

    # snapshotId = YYYYMMDD-<hash8 de sha256(articles)+sha256(indicators)+sha256(predictions)+sha256(clusters)>
    sid = str(manifest.get("snapshotId", ""))
    try:
        concat = "".join((files[n] or {})["sha256"] for n in ("articles.jsonl", "indicators.jsonl", "predictions.jsonl", "clusters.jsonl"))
        hash8 = hashlib.sha256(concat.encode("ascii")).hexdigest()[:8]
        if not sid.endswith("-" + hash8):
            errors.append(f"snapshotId no corresponde al hash de contenido (esperado sufijo {hash8})")
    except KeyError:
        errors.append("manifest sin hashes de articles/indicators/predictions/clusters")

    # Hash de predicciones de Laya: predictionsInputSha256 = sha256("{articleId}:{inputHash}\n" ordenado por articleId)
    clf = manifest.get("classifier") or {}
    expected_pred = clf.get("predictionsInputSha256")
    pred_hash: str | None = None
    verified: bool | None = None
    article_ids = [a["articleId"] for a in articles_raw]
    prediction_ids = [p["articleId"] for p in preds_raw]
    if len(set(article_ids)) != len(article_ids):
        errors.append("IDs de artículos duplicados en el snapshot")
    if preds_raw:
        pred_hash = hashlib.sha256(
            "".join(f"{p['articleId']}:{p['inputHash']}\n" for p in sorted(preds_raw, key=lambda r: r["articleId"])).encode("utf-8")
        ).hexdigest()
        verified = True
        if len(set(prediction_ids)) != len(prediction_ids) or set(prediction_ids) != set(article_ids):
            verified = False
            errors.append("predicciones duplicadas o cobertura incompleta de artículos")
        if expected_pred and expected_pred != pred_hash:
            verified = False
            errors.append("predictionsInputSha256 del manifest no coincide con las predicciones publicadas")
        if not expected_pred:
            verified = False
            errors.append("manifest sin classifier.predictionsInputSha256")
        art_by_id = {a["articleId"]: a for a in articles_raw}
        mismatched = 0
        missing_art = 0
        for p in preds_raw:
            a = art_by_id.get(p["articleId"])
            if a is None:
                missing_art += 1
            elif prediction_input_hash(a["title"]) != p["inputHash"]:
                mismatched += 1
        if missing_art:
            verified = False
            errors.append(f"{missing_art} predicciones sin artículo en el snapshot")
        if mismatched:
            verified = False
            errors.append(f"{mismatched} predicciones cuyo inputHash no corresponde al titular del snapshot")
        arts_sha = clf.get("articlesSha256")
        if arts_sha and arts_sha != (files.get("articles.jsonl") or {}).get("sha256"):
            verified = False
            errors.append("classifier.articlesSha256 no coincide con el hash de articles.jsonl")
    elif articles_raw:
        verified = False
        errors.append("predicciones ausentes para los artículos del snapshot")
    return IntegrityReport(
        manifest_verified=not [e for e in errors if "predicci" not in e and "classifier" not in e],
        files_checked=checked,
        predictions_hash_verified=verified,
        predictions_sha256=pred_hash,
        errors=errors,
        checked_at=datetime.now(UTC),
    )


def resolve_snapshot_dir(settings: Settings) -> Path:
    if settings.snapshot_dir:
        return settings.snapshot_dir
    root = settings.snapshots_root
    current = root / "CURRENT"
    if current.is_file():  # puntero publicado por `datos`
        name = current.read_text(encoding="utf-8").strip()
        target = root / name
        if not name or not target.resolve().is_relative_to(root.resolve()):
            raise RuntimeError("CURRENT debe apuntar a un snapshot dentro de UMBRAL_SNAPSHOTS_ROOT.")
        if (target / "manifest.json").exists():
            return target
        raise FileNotFoundError("El snapshot señalado por CURRENT no existe; no se cambiarán datos implícitamente.")
    candidates: list[tuple[str, Path]] = []
    if root.is_dir():
        for d in root.iterdir():
            mf = d / "manifest.json"
            if d.is_dir() and mf.exists():
                try:
                    created = json.loads(mf.read_text(encoding="utf-8")).get("createdAt", "")
                except (OSError, ValueError):
                    created = ""
                candidates.append((created or d.name, d))
    if candidates:
        candidates.sort(key=lambda t: t[0])
        return candidates[-1][1]
    if settings.allow_fixture and FIXTURE_DIR.is_dir():
        return FIXTURE_DIR
    raise FileNotFoundError(
        f"No hay snapshot en {root} y el fixture está deshabilitado (UMBRAL_ALLOW_FIXTURE=0 o ausente)."
    )


def _find_metrics(path: Path, snapshot_id: str) -> dict[str, Any] | None:
    for cand in (path / "metrics.json", repo_root() / "eval" / "results" / "latest.json", repo_root() / "eval" / "metrics.json"):
        if cand.exists():
            try:
                metrics = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(metrics, dict) and metrics.get("snapshotId") == snapshot_id:
                    return metrics
            except (OSError, ValueError):
                continue
    return None


def load_corpus(settings: Settings) -> Corpus:
    path = resolve_snapshot_dir(settings)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    articles_raw = read_jsonl(path / "articles.jsonl")
    preds_raw = read_jsonl(path / "predictions.jsonl")
    clusters_raw = read_jsonl(path / "clusters.jsonl")
    indicators_raw = read_jsonl(path / "indicators.jsonl")
    qr_path = path / "quality_report.json"
    quality = json.loads(qr_path.read_text(encoding="utf-8")) if qr_path.exists() else None

    integrity = _verify_integrity(path, manifest, articles_raw, preds_raw)
    article_ids = {row["articleId"] for row in articles_raw}
    cluster_ids = [row["clusterId"] for row in clusters_raw]
    members = [aid for row in clusters_raw for aid in row.get("memberArticleIds", [])]
    reference_errors = []
    if len(cluster_ids) != len(set(cluster_ids)):
        reference_errors.append("IDs de grupos duplicados")
    if set(members) != article_ids or len(members) != len(article_ids):
        reference_errors.append("Cada artículo debe pertenecer exactamente a un grupo; hay referencias ausentes o duplicadas")
    if any(row.get("representativeArticleId") not in row.get("memberArticleIds", []) for row in clusters_raw):
        reference_errors.append("Un representante de grupo no pertenece a sus miembros")
    actual_fixtures = any(row.get("dataOrigin") == "fixture" or str(row.get(key, "")).startswith("fx_")
                          for rows, key in ((articles_raw, "articleId"), (indicators_raw, "indicatorRowId"), (preds_raw, "articleId"))
                          for row in rows)
    if actual_fixtures and manifest.get("containsFixtures") is not True:
        reference_errors.append("El manifest oculta registros fixture")
    if reference_errors:
        integrity.errors.extend(reference_errors)
        integrity.manifest_verified = False
    notes: list[str] = []
    if settings.strict_integrity and (not integrity.manifest_verified or integrity.predictions_hash_verified is False):
        raise RuntimeError("Integridad del snapshot inválida: " + "; ".join(integrity.errors))
    if integrity.errors:
        notes.append("La verificación de integridad del snapshot reportó errores; los datos se sirven marcados como no verificados.")

    semantic = None
    if settings.semantic_enabled and integrity.manifest_verified and integrity.predictions_hash_verified is not False:
        semantic = load_semantic_artifacts(settings.semantic_root, path, manifest.get("snapshotId", path.name),
                                          clusters_raw, article_ids)
        if semantic.warning:
            notes.append(semantic.warning)
        elif semantic.clusters:
            clusters_raw = semantic.clusters
            notes.append("Agrupación y vecinos multilingües precalculados con MiniLM; hashes y referencias verificados.")
    events, events_metadata, events_warning = load_seismic_events(path, manifest)
    if events_warning:
        notes.append(events_warning)

    cutoff = parse_dt(manifest.get("cutoffUtc")) or datetime.now(UTC)
    preds = {p["articleId"]: p for p in preds_raw}
    cluster_of: dict[str, str] = {}
    clusters: dict[str, dict[str, Any]] = {}
    for c in clusters_raw:
        clusters[c["clusterId"]] = c
        for aid in c.get("memberArticleIds", []):
            cluster_of[aid] = c["clusterId"]

    articles: dict[str, EvidenceArticle] = {}
    for a in articles_raw:
        aid = a["articleId"]
        pred = preds.get(aid, {})
        prov = a.get("provenance") or {}
        flags: list[str] = []
        published = parse_dt(a.get("publishedAt"))
        if a.get("publishedAt") and published is None:
            flags.append("fecha_invalida")
        if published is not None and published > cutoff:
            flags.append("fecha_posterior_al_corte")
        cat = pred.get("category") or (clusters.get(cluster_of.get(aid, ""), {}).get("category")) or "indeterminado"
        if cat not in _CATEGORIES:
            cat = "indeterminado"
        geo = pred.get("geoRelevance") or "indeterminate"
        if geo not in _GEO:
            geo = "indeterminate"
        if prov.get("known") is False:
            flags.append("procedencia_desconocida")
        title = str(a.get("title", ""))
        suspicious = looks_like_instruction(title)
        if suspicious:
            flags.append("instrucciones_en_la_fuente")
        sponsored = bool(SPONSORED_RE.search(a.get("url", "") or "")) or bool(SPONSORED_RE.search(a.get("canonicalUrl", "") or ""))
        if sponsored:
            flags.append("posible_contenido_patrocinado")
        key = prov.get("key") or f"unknown:{a.get('domain') or aid}"
        articles[aid] = EvidenceArticle(
            id=aid,
            title=title,
            url=a.get("url", ""),
            domain=a.get("domain"),
            outlet=a.get("outlet") or a.get("domain") or "desconocido",
            is_tvn=bool(a.get("isTvn", False)),
            language=a.get("language"),
            published_at=published,
            published_at_basis=a.get("publishedAtBasis"),
            detected_at=parse_dt(a.get("detectedAt")),
            extracted_at=parse_dt(a.get("extractedAt")),
            category=Category(cat),
            category_probability=pred.get("probability"),
            classifier=pred.get("classifier"),
            geo_relevance=GeoRelevance(geo),
            geo_evidence=[str(x) for x in (pred.get("geoEvidence") or [])][:6],
            origin=prov.get("agency") or (a.get("outlet") or "desconocido") if prov.get("known", True) else "desconocido",
            origin_known=bool(prov.get("known", True)),
            origin_key=key,
            cluster_id=cluster_of.get(aid),
            scope_text="titular/metadatos" if a.get("textScope", "headline_metadata") == "headline_metadata" else str(a.get("textScope")),
            data_origin=a.get("dataOrigin", "real"),
            sponsored_content=sponsored,
            suspicious_instructions=suspicious,
            flags=flags,
        )

    indicators: dict[str, IndicatorPoint] = {}
    for r in indicators_raw:
        rid = r["indicatorRowId"]
        value = r.get("value")
        missing = value is None or r.get("status") == "missing"
        unit = r.get("unit")
        indicators[rid] = IndicatorPoint(
            id=rid,
            country_iso3=r["countryIso3"],
            country_name=r.get("countryName"),
            indicator_id=r["indicatorId"],
            indicator_name=r.get("indicatorName", r["indicatorId"]),
            year=int(r["year"]),
            value=None if missing else float(value),  # type: ignore[arg-type]
            unit=unit,
            source_url=r.get("sourceUrl"),
            extracted_at=parse_dt(r.get("extractedAt")),
            license=r.get("license"),
            is_missing=missing,
            data_origin=r.get("dataOrigin", "real"),
            note=(
                f"Dato anual de referencia {r['year']} ({r['countryIso3']}); no es una medición de hoy."
                if not missing
                else f"Valor ausente en la fuente para {r['countryIso3']} {r['year']}; no se rellena con cero."
            ),
        )

    contains_fixtures = bool(manifest.get("containsFixtures", False)) or actual_fixtures
    provisional = bool(manifest.get("provisional", True))
    mode = DataMode.fixture if contains_fixtures else (DataMode.provisional if provisional else DataMode.congelado)
    clf_meta = manifest.get("classifier") or {}
    if clf_meta.get("classifier") == "baseline":
        notes.append("Clasificador léxico (baseline), no Laya.")
    if mode == DataMode.fixture:
        notes.append("Datos de fixture: sintéticos, solo para pruebas y demostración del contrato.")
    return Corpus(
        path=path,
        snapshot_id=manifest.get("snapshotId", path.name),
        data_mode=mode,
        provisional=provisional,
        contains_fixtures=contains_fixtures,
        classifier=clf_meta.get("classifier"),
        cutoff=cutoff,
        manifest=manifest,
        quality_report=quality,
        metrics=_find_metrics(path, manifest.get("snapshotId", path.name)),
        sources=list(manifest.get("sources") or []),
        articles=articles,
        indicators=indicators,
        clusters=clusters,
        integrity=integrity,
        notes=notes,
        neighbors=semantic.neighbors if semantic else {},
        semantic_model=semantic.model if semantic else None,
        events=events,
        events_metadata=events_metadata,
    )
