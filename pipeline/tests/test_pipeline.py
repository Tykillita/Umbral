"""Pruebas del pipeline (sin red, sin Laya). T01-T05 y T07 sobre fixtures etiquetados."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from umbral_pipeline.build import run_build
from umbral_pipeline.classify.baseline import BaselineClassifier
from umbral_pipeline.config import CATEGORIES, INDETERMINATE
from umbral_pipeline.ingest.tvn import parse_rss
from umbral_pipeline.ingest.worldbank import build_grid, parse_wb_response
from umbral_pipeline.snapshot import verify_snapshot
from umbral_pipeline.util import canonicalize_url, date_from_url, parse_dt, read_jsonl
from umbral_pipeline.validate import detect_agency, normalize_record


# ---------- util ----------
def test_canonicalize_url_removes_tracking_www_fragment_slash():
    a = canonicalize_url("http://www.Example.com/a/b/?utm_source=x&b=2&a=1#frag")
    assert a == "https://example.com/a/b?a=1&b=2"
    assert canonicalize_url("ht!tp:/nope") is None
    assert canonicalize_url("") is None
    assert canonicalize_url("ftp://x.com/a") is None


def test_parse_dt_rejects_invalid_and_keeps_utc():
    assert parse_dt("31/02/2026") is None
    assert parse_dt("null") is None
    assert parse_dt("20260930T123000Z") == datetime(2026, 9, 30, 12, 30, tzinfo=UTC)
    assert parse_dt("Tue, 06 Oct 2026 23:57:05 +0000") == datetime(2026, 10, 6, 23, 57, 5, tzinfo=UTC)
    assert parse_dt("2026-10-06T18:00:00-05:00") == datetime(2026, 10, 6, 23, 0, tzinfo=UTC)


def test_date_from_url_pattern():
    assert date_from_url("https://x.com/2025/03/12/foo.html") == datetime(2025, 3, 12, tzinfo=UTC)
    assert date_from_url("https://x.com/nacionales/foo_1_2264701.html") is None


# ---------- ingesta ----------
RSS = """<?xml version="1.0"?><rss xmlns:dcterms="http://purl.org/dc/terms/" version="2.0"><channel>
<item><title><![CDATA[Titular uno de prueba para RSS]]></title><link><![CDATA[https://www.tvn-2.com/a_1_1.html]]></link>
<description><![CDATA[descripcion que NO se debe guardar]]></description>
<pubDate><![CDATA[Tue, 06 Oct 2026 23:57:05 +0000]]></pubDate></item></channel></rss>"""


def test_parse_rss_does_not_keep_description():
    recs = parse_rss(RSS)
    assert len(recs) == 1 and recs[0]["title"].startswith("Titular uno")
    assert "description" not in json.dumps(recs).lower() or "descripcion" not in json.dumps(recs)


def test_worldbank_grid_keeps_missing_and_has_540_rows():
    payload = [{"lastupdated": "2026-07-13"}, [
        {"indicator": {"id": "SP.POP.TOTL", "value": "Population, total"}, "date": "2024", "value": 4515577},
        {"indicator": {"id": "SP.POP.TOTL", "value": "Population, total"}, "date": "2023", "value": None},
    ]]
    parsed = parse_wb_response(payload)
    parsed["url"] = "https://example/wb"
    rows = build_grid({("PAN", "SP.POP.TOTL"): parsed}, "2026-10-07T00:00:00Z")
    assert len(rows) == 6 * 6 * 15 == 540
    by = {r["indicatorRowId"]: r for r in rows}
    assert by["ind_PAN_SP.POP.TOTL_2024"]["value"] == 4515577 and by["ind_PAN_SP.POP.TOTL_2024"]["status"] == "ok"
    assert by["ind_PAN_SP.POP.TOTL_2023"]["value"] is None and by["ind_PAN_SP.POP.TOTL_2023"]["status"] == "missing"
    assert by["ind_COL_SP.POP.TOTL_2015"]["value"] is None  # no llego: faltante, nunca 0
    assert by["ind_PAN_SP.POP.TOTL_2024"]["unit"] == "personas" and by["ind_PAN_SP.POP.TOTL_2024"]["year"] == 2024


# ---------- validacion (T01) ----------
CUT = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
WIN = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _norm(raw):
    return normalize_record(raw, window_start=WIN, cutoff=CUT, extracted_default="2026-10-07T12:00:00Z")


@pytest.mark.parametrize(
    "raw,code",
    [
        ({"title": None, "url": None}, "empty_row"),
        ({"title": "Titular válido de prueba", "url": "https://a.example/x", "publishedRaw": "31/02/2026"}, "invalid_date"),
        ({"title": "Titular válido de prueba", "url": "https://a.example/x"}, "null_date"),
        ({"title": "Titular válido de prueba", "url": None, "publishedRaw": "2026-10-01T00:00:00Z"}, "missing_url"),
        ({"title": "Titular válido de prueba", "url": "no-es-url", "publishedRaw": "2026-10-01T00:00:00Z"}, "invalid_url"),
        ({"title": "x", "url": "https://a.example/x", "publishedRaw": "2026-10-01T00:00:00Z"}, "missing_title"),
        ({"title": "Titular válido de prueba", "url": "https://a.example/x", "publishedRaw": "2031-01-01T00:00:00Z"}, "invalid_date"),
        ({"title": "Titular válido de prueba", "url": "https://a.example/x", "publishedRaw": "2024-03-01T00:00:00Z"}, "date_out_of_window"),
    ],
)
def test_t01_invalid_rows_are_rejected_with_code(raw, code):
    art, rej = _norm(raw)
    assert art is None and rej is not None and code in rej["reasonCodes"]


def test_t01_null_published_is_kept_when_detection_known():
    art, rej = _norm({"title": "Titular válido de prueba", "url": "https://a.example/x", "detectedRaw": "20261001T120000Z"})
    assert rej is None and art is not None
    assert art["publishedAt"] is None and art["publishedAtBasis"] == "unknown" and art["detectedAt"] == "2026-10-01T12:00:00Z"
    assert art["textScope"] == "headline_metadata"


def test_article_id_is_deterministic_from_canonical_url():
    r = {"title": "Titular válido de prueba", "url": "https://www.a.example/x/?utm_source=a", "publishedRaw": "2026-10-01T00:00:00Z"}
    r2 = {"title": "Otro titular distinto de prueba", "url": "http://a.example/x", "publishedRaw": "2026-10-02T00:00:00Z"}
    assert _norm(r)[0]["articleId"] == _norm(r2)[0]["articleId"]


def test_agency_detection_only_as_signature():
    assert detect_agency("Sismo en Panamá - EFE", "", "x.com") == "efe"
    assert detect_agency("Sismo en Panamá (AFP)", "", "x.com") == "afp"
    assert detect_agency("La efe es una letra del alfabeto", "", "x.com") is None
    assert detect_agency("El AP de la CSS crece", "", "x.com") is None


# ---------- baseline ----------
def test_baseline_categories_and_indeterminate():
    arts = [
        {"articleId": "a1", "title": "Inflación y empleo en Panamá: el PIB crece", "isTvn": False, "sourceCountry": None},
        {"articleId": "a2", "title": "Se registra un sismo de magnitud 5 en Chiriquí", "isTvn": False, "sourceCountry": None},
        {"articleId": "a3", "title": "Hola mundo sin tema alguno reconocible", "isTvn": False, "sourceCountry": None},
    ]
    preds = BaselineClassifier().predict(arts)
    assert [p["category"] for p in preds] == ["economia", "eventos_naturales", INDETERMINATE]
    assert all(p["classifier"] == "baseline" and p["modelId"] == "baseline-lexical-v1" for p in preds)
    assert all(set(p["probabilities"]) == set(CATEGORIES) for p in preds)
    assert abs(sum(preds[0]["probabilities"].values()) - 1) < 1e-3
    assert preds[1]["geoRelevance"] == "panama"


# ---------- snapshot de fixtures (T01-T05, T07) ----------
@pytest.fixture(scope="module")
def snap() -> Path:
    # no usamos tmp_path: en algunas maquinas Windows %TEMP%\pytest-of-* no es escribible
    d = Path(__file__).resolve().parents[1] / ".pytest_cache" / "snapdata"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return run_build(d, raw_dir=None, classifier="baseline", use_fixtures=True, fixtures_only=True, log=lambda *_: None)


def test_snapshot_verifies_and_is_labeled(snap):
    ok, problems = verify_snapshot(snap)
    assert ok, problems
    m = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    assert m["provisional"] is True and m["containsFixtures"] is True
    assert m["classifier"]["classifier"] == "baseline"
    assert m["snapshotId"] == snap.name and len(m["snapshotId"].split("-")[1]) == 8
    assert m["counts"]["indicatorRows"] == 540
    assert all(a["dataOrigin"] == "fixture" for a in read_jsonl(snap / "articles.jsonl"))


def test_snapshot_tamper_detected(snap):
    f = snap / "articles.jsonl"
    original = f.read_bytes()
    f.write_bytes(original.replace(b"Sismo", b"Sismx", 1))
    try:
        ok, problems = verify_snapshot(snap)
        assert not ok and any("SHA-256" in p for p in problems)
    finally:
        f.write_bytes(original)
    assert verify_snapshot(snap)[0]


def test_t01_separates_invalid_without_blocking(snap):
    inv = list(read_jsonl(snap / "invalid.jsonl"))
    codes = {c for r in inv for c in r["reasonCodes"]}
    assert {"empty_row", "invalid_date", "null_date", "missing_url", "invalid_url", "missing_title"} <= codes
    arts = list(read_jsonl(snap / "articles.jsonl"))
    assert any(a["publishedAt"] is None for a in arts)  # nulo conservado
    q = json.loads((snap / "quality_report.json").read_text(encoding="utf-8"))
    assert q["news"]["invalid"] == len(inv) and q["news"]["valid"] == len(arts)


def test_t02_same_event_grouped_without_tripling_corroboration(snap):
    clusters = list(read_jsonl(snap / "clusters.jsonl"))
    big = [c for c in clusters if c["size"] == 3]
    assert len(big) == 1
    assert big[0]["independentProvenanceCount"] == 1  # agencia replicada = 1 procedencia
    assert big[0]["outletCount"] == 3


def test_t03_recirculation_keeps_original_date(snap):
    rec = [c for c in read_jsonl(snap / "clusters.jsonl") if c["isRecirculation"]]
    assert len(rec) == 1 and rec[0]["originalPublishedAt"].startswith("2025-03-12")


def test_t05_contradiction_candidates_across_clusters(snap):
    cands = [c for c in read_jsonl(snap / "clusters.jsonl") if c["hasContradictionCandidate"]]
    assert len(cands) == 2 and cands[0]["contradictionCandidateIds"]


def test_t07_injection_title_is_plain_data(snap):
    arts = [a for a in read_jsonl(snap / "articles.jsonl") if "IGNORA TUS INSTRUCCIONES" in a["title"]]
    assert len(arts) == 1 and arts[0]["dataOrigin"] == "fixture" and arts[0]["articleId"].startswith("fx_")


def test_predictions_input_hash_matches_title(snap):
    from umbral_pipeline.classify import input_hash

    arts = {a["articleId"]: a for a in read_jsonl(snap / "articles.jsonl")}
    for p in read_jsonl(snap / "predictions.jsonl"):
        assert p["inputHash"] == input_hash(arts[p["articleId"]])


# ---------- control de alcance de Laya (sin cargar el modelo) ----------
def test_scope_question_has_explicit_out_of_scope_option_and_decision_mapping():
    from umbral_pipeline.classify.laya_clf import CATEGORY_QUESTION, decide_category

    crit = CATEGORY_QUESTION["category"]["criteria"]
    assert set(crit) == set(CATEGORIES) | {"otro"}
    assert "sucesos policiales" in crit["otro"] and "deportes" in crit["otro"]
    assert decide_category({"economia": 0.2, "otro": 0.7, "turismo": 0.1}, 0.5) == (INDETERMINATE, 0.7)
    assert decide_category({"economia": 0.8, "otro": 0.2}, 0.5) == ("economia", 0.8)
    assert decide_category({"economia": 0.4, "otro": 0.35, "turismo": 0.25}, 0.5)[0] == INDETERMINATE  # bajo umbral


def test_independent_provenance_collapses_copies_with_added_prefix():
    from umbral_pipeline.cluster import independent_provenance, norm_title

    def art(i, dom, title):
        return {"articleId": i, "title": title, "provenance": {"key": f"outlet:{dom}"}}

    arts = [
        art("a", "uno.example", "Detienen a tres dominicanos acusados de reclutar personas para la guerra"),
        art("b", "dos.example", "En Panamá: Detienen a tres dominicanos acusados de reclutar personas para la guerra"),
        art("c", "tres.example", "Una redacción distinta informa de otro enfoque sobre el mismo suceso en Panamá hoy"),
    ]
    normed = {a["articleId"]: norm_title(a["title"]) for a in arts}
    assert independent_provenance(arts, normed) == 2  # a y b son copia; c es distinto


# ---------- relevancia geográfica por contenido (lexical-content-v2) ----------
def _g(title, domain="x.example", tvn=False, country=None):
    from umbral_pipeline.classify.geo import geo_content_v2

    return geo_content_v2({"title": title, "domain": domain, "isTvn": tvn, "sourceCountry": country})[0]


def test_geo_content_rule_not_driven_by_outlet():
    # TVN + contenido extranjero => sin relación (el caso de «Trump no reembolsará…»)
    assert _g("Trump no reembolsará a los contribuyentes el dinero usado para anuncios de TV", "tvn-2.com", True) == "none"
    # nombra Panamá / lugar panameño / balboas => panama aunque el medio sea extranjero
    assert _g("Panamá refuerza su promoción turística en Argentina", "prensa-latina.cu") == "panama"
    assert _g("Aprueban B /. 600 millones para obras en Chiriquí", "x.example") == "panama"
    assert _g("巴拿马经济强劲复苏 外资重返债券市场", "finance.sina.cn") == "panama"
    # región del PDF => regional; Panamericano no cuenta como Panamá
    assert _g("Costa Rica anuncia nuevas tarifas eléctricas", "tvn-2.com", True) == "regional"
    assert _g("Juegos Panamericanos arrancan en Lima", "x.example") == "none"
    # fuente panameña sin nada extranjero => local; fuente extranjera sin señal => indeterminado
    assert _g("Comisión de Presupuesto tramita traslados y créditos", "tvn-2.com", True) == "panama"
    assert _g("Se inicia formalmente la feria del libro", "diariolibre.com", country="Dominican Republic") == "indeterminate"


def test_numbers_conflict_ignores_omitted_figures():
    from umbral_pipeline.cluster import numbers_conflict, numbers_in

    assert not numbers_conflict(numbers_in("Canal aumenta a 33 tránsitos y calado de 49 pies"), numbers_in("Canal aumenta a 33 tránsitos"))
    assert numbers_conflict(numbers_in("Panamá crecerá 4,5 % en 2026"), numbers_in("Panamá crecerá 2,8 % en 2026"))
    assert not numbers_conflict(set(), {"3"})


def test_geo_foreign_demonyms_block_local_source_rule():
    assert _g("Sánchez presenta ante el Congreso español decretos de vivienda", "tvn-2.com", True) == "none"
    assert _g("Asamblea Nacional discute el proyecto de ley de vivienda", "tvn-2.com", True) == "panama"
