"""Exportacion del snapshot, manifest con SHA-256, diccionario de datos, condiciones de uso y verificacion."""

from __future__ import annotations

import csv
import json
import platform
import shutil
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__
from .config import COUNTRIES, INDICATORS, SOURCE_TERMS, YEARS
from .util import iso_z, now_utc, read_jsonl, sha256_file, sha256_hex, write_json, write_jsonl

CONTENT_FILES = ["articles.jsonl", "indicators.jsonl", "predictions.jsonl", "clusters.jsonl"]


def _w(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Escribe texto con LF (hash identico en Windows y Linux)."""
    with path.open("w", encoding=encoding, newline="\n") as fh:
        fh.write(text)


def predictions_input_sha256(articles: list[dict[str, Any]] | None, predictions: list[dict[str, Any]]) -> str:
    lines = sorted(f"{p['articleId']}:{p['inputHash']}\n" for p in predictions)
    return sha256_hex("".join(lines))


def compute_snapshot_id(cutoff: datetime, file_hashes: dict[str, str]) -> str:
    joined = "".join(file_hashes[f] for f in CONTENT_FILES)
    return f"{cutoff:%Y%m%d}-{sha256_hex(joined)[:8]}"


def _write_csvs(out: Path, articles: list[dict[str, Any]], indicators: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    with (out / "noticias.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["id_noticia", "titulo", "url", "medio", "idioma", "fecha_publicacion", "fecha_deteccion",
                    "fecha_extraccion", "tema", "origen", "alcance_texto"])
        for a in articles:
            w.writerow([a["articleId"], a["title"], a["url"], a["outlet"], a["language"] or "", a["publishedAt"] or "",
                        a["detectedAt"] or "", a["extractedAt"], a["topicHint"] or "", a["origin"]["source"], a["textScope"]])
    with (out / "indicadores.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["pais_iso3", "indicador_id", "anio", "valor", "unidad", "fuente_url", "fecha_extraccion", "licencia"])
        for r in indicators:
            w.writerow([r["countryIso3"], r["indicatorId"], r["year"], "" if r["value"] is None else repr(r["value"]),
                        r["unit"], r["sourceUrl"], r["extractedAt"], r["license"]])
    write_json(out / "fuentes.json", sources)


DICTIONARY_MD = """# Diccionario de datos del snapshot

Contrato completo y versionado: `docs/contracts/snapshot-schema.md` (schemaVersion {schema}). Resumen:

| Archivo | Registros | Clave | Descripción |
|---|---|---|---|
| `articles.jsonl` | {n_articles} | `articleId` | Noticias válidas (titular + metadatos). Sin cuerpos ni descripciones. |
| `indicators.jsonl` | {n_ind} | `indicatorRowId` | Cuadrícula Banco Mundial 6 países × 6 indicadores × 15 años (2010–2024); faltantes con `value=null`. |
| `predictions.jsonl` | {n_pred} | `predictionId` | Categoría (6 + `indeterminado`), probabilidad, relevancia geográfica, modelo, versión, fecha y `inputHash`. |
| `clusters.jsonl` | {n_clu} | `clusterId` | Grupos de duplicados/evento; procedencias independientes; recirculación. |
| `invalid.jsonl` | {n_inv} | `rejectId` | Registros rechazados con códigos de motivo (T01). |
| `quality_report.json` | – | – | Reporte de calidad de la carga. |
| `manifest.json` / `SHA256SUMS` | – | – | Inventario con SHA-256, ventana, consultas, clasificador. |
| `noticias.csv`, `indicadores.csv`, `fuentes.json` | – | – | Vista compatible con el contrato de archivos del PDF §7. |
| `events.geojson` | {n_ev} | `id` | (Opcional) sismos USGS 2024 en la caja regional del PDF §6C. |

## Reglas
- Fechas ISO 8601 en UTC (`Z`). `publishedAt` es publicación; `detectedAt` es la detección de GDELT (`seendate`) y **no** es publicación.
- GDELT no entrega fecha de publicación: `publishedAt` es `null` salvo patrón de fecha en la URL (`publishedAtBasis = url_pattern`).
- Nulos conservados; nunca se rellenan con 0. Unidades originales en `unit`.
- `textScope = headline_metadata`: toda salida debe decir «basado únicamente en titular/metadatos».
- `dataOrigin = fixture` marca datos sintéticos (prefijo `fx_`); jamás se mezclan sin etiqueta.
- La clasificación no es verdad/falsedad. `category` indica tema; `probability` no está calibrada.
"""


def terms_md(sources: list[dict[str, Any]]) -> str:
    lines = ["# Condiciones de uso por fuente", "", "No se redistribuyen artículos, imágenes ni videos. Este paquete contiene metadatos (titular, URL, fechas) y datos estadísticos con atribución.", ""]
    for s in sources:
        lines += [f"## {s['name']}", f"- URL: {s['url']}", f"- Licencia: {s['license']}", f"- Condiciones: {s['terms']}", f"- Extraído: {s.get('extractedAt') or 'n/d'}", ""]
    return "\n".join(lines)


def export_snapshot(
    data_dir: Path,
    *,
    cutoff: datetime,
    window: dict[str, Any],
    queries: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    indicators: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    invalid: list[dict[str, Any]],
    quality: dict[str, Any],
    classifier_info: dict[str, Any],
    events_geojson: dict[str, Any] | None,
    contains_fixtures: bool,
    provisional_reasons: list[str],
    sources_extracted: dict[str, str | None],
    transformations: list[str],
    version: str = "1.0.0",
    set_current: bool = True,
) -> Path:
    snaps = data_dir / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    tmp = snaps / f"_tmp_build_{uuid.uuid4().hex}"
    tmp.mkdir()

    write_jsonl(tmp / "articles.jsonl", articles)
    write_jsonl(tmp / "indicators.jsonl", indicators)
    write_jsonl(tmp / "predictions.jsonl", predictions)
    write_jsonl(tmp / "clusters.jsonl", clusters)
    write_jsonl(tmp / "invalid.jsonl", invalid)
    if events_geojson is not None:
        _w(tmp / "events.geojson", json.dumps(events_geojson, ensure_ascii=False), encoding="utf-8")

    hashes = {f: sha256_file(tmp / f) for f in CONTENT_FILES}
    snapshot_id = compute_snapshot_id(cutoff, hashes)

    sources = []
    for key, t in SOURCE_TERMS.items():
        if key == "usgs" and events_geojson is None:
            continue
        sources.append({"id": key, **t, "extractedAt": sources_extracted.get(key),
                        "transformations": [x for x in transformations if x]})
    if contains_fixtures:
        sources.append({"id": "fixture", "name": "Fixtures sintéticos (T01–T04, T07)", "url": "pipeline/umbral_pipeline/fixtures.py",
                        "license": "Sintéticos del equipo (MIT)", "terms": "Dominios .example/.invalid; no representan noticias reales.",
                        "extractedAt": iso_z(cutoff), "transformations": []})

    _write_csvs(tmp, articles, indicators, sources)

    quality = {**quality, "snapshotId": snapshot_id}
    write_json(tmp / "quality_report.json", quality)
    _w(tmp / "DATA_DICTIONARY.md", 
        DICTIONARY_MD.format(schema=SCHEMA_VERSION, n_articles=len(articles), n_ind=len(indicators), n_pred=len(predictions),
                             n_clu=len(clusters), n_inv=len(invalid),
                             n_ev=len(events_geojson["features"]) if events_geojson else 0), encoding="utf-8")
    _w(tmp / "TERMS_OF_USE.md", terms_md(sources), encoding="utf-8")

    other_files = ["invalid.jsonl", "quality_report.json", "noticias.csv", "indicadores.csv", "fuentes.json",
                   "DATA_DICTIONARY.md", "TERMS_OF_USE.md"] + (["events.geojson"] if events_geojson else [])
    files: dict[str, Any] = {}
    counts_lines = {"articles.jsonl": len(articles), "indicators.jsonl": len(indicators), "predictions.jsonl": len(predictions),
                    "clusters.jsonl": len(clusters), "invalid.jsonl": len(invalid)}
    for f in CONTENT_FILES + other_files:
        files[f] = {"sha256": sha256_file(tmp / f), "bytes": (tmp / f).stat().st_size, "records": counts_lines.get(f)}
    if events_geojson:
        files["events.geojson"]["records"] = len(events_geojson["features"])

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "snapshotId": snapshot_id,
        "version": version,
        "provisional": bool(provisional_reasons),
        "provisionalReasons": provisional_reasons,
        "containsFixtures": contains_fixtures,
        "cutoffUtc": iso_z(cutoff),
        "createdAt": iso_z(now_utc()),
        "pipeline": {"name": "umbral_pipeline", "version": __version__, "python": platform.python_version()},
        "window": window,
        "queries": queries,
        "files": files,
        "counts": {
            "articlesValid": len(articles), "articlesInvalid": len(invalid),
            "tvn": sum(1 for a in articles if a["isTvn"]), "gdelt": sum(1 for a in articles if a["origin"]["source"] == "gdelt_doc"),
            "fixture": sum(1 for a in articles if a["dataOrigin"] == "fixture"),
            "indicatorRows": len(indicators), "indicatorValues": sum(1 for r in indicators if r["value"] is not None),
            "clusters": len(clusters), "predictions": len(predictions),
        },
        "classifier": {**classifier_info, "predictionsInputSha256": predictions_input_sha256(articles, predictions),
                       "articlesSha256": hashes["articles.jsonl"]},
        "sources": sources,
        "licenseNotes": "Solo metadatos de noticias (sin cuerpos); Banco Mundial CC BY 4.0 con atribución; USGS dominio público. Ver TERMS_OF_USE.md.",
        "transformations": transformations,
        "snapshotHashInputs": "sha256(articles)+sha256(indicators)+sha256(predictions)+sha256(clusters)",
    }
    write_json(tmp / "manifest.json", manifest)
    sums = [f"{sha256_file(tmp / f)} *{f}" for f in sorted(["manifest.json"] + CONTENT_FILES + other_files)]
    _w(tmp / "SHA256SUMS", "\n".join(sums) + "\n")

    final = snaps / snapshot_id
    if final.exists():
        ok, problems = verify_snapshot(final)
        if not ok:
            raise ValueError(f"El snapshot existente está corrupto: {'; '.join(problems)}")
        shutil.rmtree(tmp)
    else:
        tmp.rename(final)
    if set_current:
        activate_snapshot(final)
    return final


def activate_snapshot(snapshot_dir: Path) -> None:
    """Activa únicamente un corte verificado con reemplazo atómico de CURRENT."""
    ok, problems = verify_snapshot(snapshot_dir)
    if not ok:
        raise ValueError(f"El snapshot no se activa: {'; '.join(problems)}")
    current = snapshot_dir.parent / "CURRENT"
    candidate = current.with_name(f".CURRENT-{uuid.uuid4().hex}")
    _w(candidate, snapshot_dir.name + "\n")
    candidate.replace(current)


def verify_snapshot(snap: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    mpath = snap / "manifest.json"
    if not mpath.exists():
        return False, ["falta manifest.json"]
    m = json.loads(mpath.read_text(encoding="utf-8"))
    hashes: dict[str, str] = {}
    for name, info in m["files"].items():
        if Path(name).name != name or "/" in name or "\\" in name:
            problems.append(f"ruta de archivo no permitida: {name}")
            continue
        p = snap / name
        if not p.exists():
            problems.append(f"falta {name}")
            continue
        h = sha256_file(p)
        hashes[name] = h
        if h != info["sha256"]:
            problems.append(f"SHA-256 distinto en {name}")
    if all(f in hashes for f in CONTENT_FILES):
        expect = compute_snapshot_id(datetime.fromisoformat(m["cutoffUtc"].replace("Z", "+00:00")), hashes)
        if expect != m["snapshotId"]:
            problems.append(f"snapshotId esperado {expect} != {m['snapshotId']}")
        if snap.name != m["snapshotId"]:
            problems.append(f"nombre de carpeta {snap.name} != snapshotId")
    sums = snap / "SHA256SUMS"
    if sums.exists():
        for line in sums.read_text(encoding="utf-8").splitlines():
            h, _, name = line.partition(" *")
            if name and (snap / name).exists() and sha256_file(snap / name) != h:
                problems.append(f"SHA256SUMS no coincide: {name}")
    try:
        arts = list(read_jsonl(snap / "articles.jsonl"))
        preds = list(read_jsonl(snap / "predictions.jsonl"))
        clus = list(read_jsonl(snap / "clusters.jsonl"))
        inds = list(read_jsonl(snap / "indicators.jsonl"))
    except Exception as exc:  # noqa: BLE001
        return False, problems + [f"no se pudo leer: {exc}"]
    ids = {a["articleId"] for a in arts}
    actual_fixtures = any(a.get("dataOrigin") == "fixture" for a in arts) or any(
        r.get("dataOrigin") == "fixture" for r in inds)
    if actual_fixtures != bool(m.get("containsFixtures")):
        problems.append("containsFixtures no corresponde a los registros")
    if len(ids) != len(arts):
        problems.append("articleId duplicados")
    pred_ids = [p["articleId"] for p in preds]
    if set(pred_ids) != ids or len(pred_ids) != len(ids):
        problems.append("predicciones no cubren exactamente los artículos")
    in_cluster = [x for c in clus for x in c["memberArticleIds"]]
    if sorted(in_cluster) != sorted(ids):
        problems.append("clusters no particionan los artículos")
    if m["classifier"]["predictionsInputSha256"] != predictions_input_sha256(arts, preds):
        problems.append("predictionsInputSha256 no coincide")
    if m["classifier"].get("articlesSha256") != hashes.get("articles.jsonl"):
        problems.append("classifier.articlesSha256 no coincide con articles.jsonl")
    by_art = {a["articleId"]: a for a in arts}
    from .classify import input_hash

    bad_hash = [p["articleId"] for p in preds if p["articleId"] in by_art and input_hash(by_art[p["articleId"]]) != p["inputHash"]]
    if bad_hash:
        problems.append(f"{len(bad_hash)} inputHash no corresponden al titular actual")
    if len(inds) != len(COUNTRIES) * len(INDICATORS) * len(YEARS):
        problems.append(f"indicadores: {len(inds)} filas != {len(COUNTRIES) * len(INDICATORS) * len(YEARS)}")
    if any(r["value"] is None and r["status"] != "missing" for r in inds):
        problems.append("indicadores con valor nulo y status != missing")
    if Counter(p["classifier"] for p in preds).keys() - {m["classifier"]["classifier"]}:
        problems.append("classifier de predicciones distinto al del manifest")
    return (not problems), problems
