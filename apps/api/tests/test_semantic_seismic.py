"""Integridad semántica, búsqueda multilingüe, candidatos T05 y catálogo sísmico sin daños inventados."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from umbral_api.app import create_app
from umbral_api.compose import (
    ComposeCitation,
    ComposeStatement,
    ModelCompose,
    pack_from_response,
    validate_composition,
)
from umbral_api.config import Settings
from umbral_api.models import QueryIntent, QueryRequest
from umbral_api.retrieval import Doc, SearchIndex
from umbral_api.services import Services
from umbral_api.snapshot import load_corpus, prediction_input_hash, read_jsonl, sha256_file
from umbral_api.topics import cross_contradictions, detect_contradictions, numeric_claims

from .conftest import FakeProvider


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def rows(path: Path, data) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in data), encoding="utf-8")


def seal_snapshot(path: Path) -> dict:
    predictions = read_jsonl(path / "predictions.jsonl")
    articles = {row["articleId"]: row for row in read_jsonl(path / "articles.jsonl")}
    for row in predictions:
        row["inputHash"] = prediction_input_hash(articles[row["articleId"]]["title"])
    rows(path / "predictions.jsonl", predictions)
    files = {name: {"sha256": sha256_file(path / name)} for name in
             ("articles.jsonl", "indicators.jsonl", "predictions.jsonl", "clusters.jsonl", "events.geojson")}
    core = "".join(files[name]["sha256"] for name in ("articles.jsonl", "indicators.jsonl", "predictions.jsonl", "clusters.jsonl"))
    manifest = {"snapshotId": "20261007-" + hashlib.sha256(core.encode("ascii")).hexdigest()[:8],
                "cutoffUtc": "2026-10-07T12:00:00Z", "containsFixtures": True, "provisional": True, "files": files,
                "classifier": {"classifier": "baseline", "articlesSha256": files["articles.jsonl"]["sha256"],
                               "predictionsInputSha256": hashlib.sha256("".join(f"{p['articleId']}:{p['inputHash']}\n" for p in sorted(predictions, key=lambda p: p["articleId"])).encode()).hexdigest()}}
    dump(path / "manifest.json", manifest)
    return manifest


@pytest.fixture
def sample(tmp_path):
    snapshot, semantic_root = tmp_path / "snapshot", tmp_path / "agrupacion"
    snapshot.mkdir()
    articles = []
    titles = {"fx_sp": "El Canal de Panamá anuncia restricciones de calado por baja del lago Gatún",
              "fx_en": "Shipping restrictions imposed as reservoir levels decline",
              "fx_other": "Parlamento discute presupuesto de servicios municipales"}
    for aid, title in titles.items():
        articles.append({"articleId": aid, "title": title, "url": f"https://fixture.example/{aid}",
                         "outlet": f"Medio {aid} (fixture)", "domain": "fixture.example", "language": "en" if aid == "fx_en" else "es",
                         "publishedAt": "2026-10-06T12:00:00Z", "extractedAt": "2026-10-07T11:00:00Z", "dataOrigin": "fixture",
                         "provenance": {"key": f"outlet:{aid}", "known": True}})
    clusters = [{"clusterId": f"fx_evt_{aid}", "memberArticleIds": [aid], "representativeArticleId": aid,
                 "size": 1, "category": "logistica_canal" if aid != "fx_other" else "servicios_publicos", "links": []} for aid in titles]
    rows(snapshot / "articles.jsonl", articles)
    rows(snapshot / "clusters.jsonl", clusters)
    rows(snapshot / "indicators.jsonl", [])
    rows(snapshot / "predictions.jsonl", [{"articleId": aid, "inputHash": "", "category": "logistica_canal",
                                           "geoRelevance": "panama", "classifier": "baseline"} for aid in titles])
    events = []
    for eid, magnitude, time, place in (("fx_low", 3.1, "2024-05-10T02:00:00Z", "south of Panama"),
                                       ("fx_high", 5.5, "2024-04-03T01:30:00Z", "19 km west of Costa Rica")):
        events.append({"type": "Feature", "id": eid,
                       "properties": {"id": eid, "magnitude": magnitude, "time": time, "place": place,
                                      "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{eid}"},
                       "geometry": {"type": "Point", "coordinates": [-82, 8, 10]}})
    dump(snapshot / "events.geojson", {"type": "FeatureCollection", "features": events,
                                        "metadata": {"source": "fixture", "query": {"starttime": "2024-01-01", "endtime": "2024-12-31"}}})
    manifest = seal_snapshot(snapshot)
    folder = semantic_root / manifest["snapshotId"]
    folder.mkdir(parents=True)
    merged = dict(clusters[0], clusterId="fx_evt_merged", memberArticleIds=["fx_sp", "fx_en"], size=2,
                  mergedFromClusterIds=[clusters[0]["clusterId"], clusters[1]["clusterId"]],
                  links=[{"a": "fx_sp", "b": "fx_en", "method": "semantic_embedding", "score": 0.9}])
    rows(folder / "clusters.semantic.jsonl", [merged, clusters[2]])
    rows(folder / "neighbors.semantic.jsonl", [{"articleId": aid, "neighbors": [[other, 0.9]] if other else []}
                                                for aid, other in (("fx_sp", "fx_en"), ("fx_en", "fx_sp"), ("fx_other", None))])
    common = {"schemaVersion": 1, "snapshotId": manifest["snapshotId"], "model": "MiniLM-fixture", "modelRevision": "fixture",
              "generatedAt": "2026-10-07T12:30:00Z", "sourceArticlesSha256": sha256_file(snapshot / "articles.jsonl"),
              "sourceClustersSha256": sha256_file(snapshot / "clusters.jsonl")}
    dump(folder / "meta.json", common | {"clustersSha256": sha256_file(folder / "clusters.semantic.jsonl")})
    dump(folder / "meta.neighbors.json", common | {"neighborsSha256": sha256_file(folder / "neighbors.semantic.jsonl")})
    settings = Settings(snapshot_dir=snapshot, semantic_root=semantic_root, persistence="memory", auth_mode="dev-header", offline=True)
    return settings, folder


def client_for(settings: Settings) -> tuple[TestClient, Services]:
    service = Services(settings)
    return TestClient(create_app(settings, services=service), headers={"X-Umbral-User": "revision"}), service


def test_complete_semantic_package_activates_and_groups_translated_event(sample):
    settings, _ = sample
    corpus = load_corpus(settings)
    assert corpus.integrity.manifest_verified and corpus.semantic_model == "MiniLM-fixture"
    assert len(corpus.clusters) == 2 and corpus.articles["fx_sp"].cluster_id == corpus.articles["fx_en"].cluster_id
    client, _ = client_for(settings)
    response = client.post("/api/v1/queries", json={"question": "restricciones de calado del Canal lago Gatún"}).json()
    assert response["answerStatus"] == "respondida" and response["retrieval"]["method"] == "bm25+rapidfuzz+semantic-rrf"
    assert response["retrieval"]["semanticModel"] == "MiniLM-fixture" and response["retrieval"]["rrfK"] == 60
    translated = next(hit for hit in response["hits"] if hit["evidenceId"] == "fx_en")
    assert translated["retrievalOrigin"] == "semantic_neighbor" and translated["literalCoverage"] == 0
    assert translated["semanticAnchorId"] == "fx_sp" and translated["semanticSimilarity"] == 0.9
    assert {citation["evidenceId"] for citation in response["citations"]} == {"fx_sp", "fx_en"}


@pytest.mark.parametrize("mutation", ["missing", "hash", "source", "reference", "duplicate", "nan", "self", "partition", "snapshot"])
def test_invalid_semantic_package_returns_original_lexical_corpus(sample, mutation):
    settings, folder = sample
    if mutation == "missing":
        (folder / "meta.neighbors.json").unlink()
    elif mutation == "hash":
        with (folder / "neighbors.semantic.jsonl").open("a", encoding="utf-8") as file:
            file.write("{}\n")
    elif mutation in {"source", "snapshot"}:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        meta["sourceArticlesSha256" if mutation == "source" else "snapshotId"] = "otro"
        dump(folder / "meta.json", meta)
    elif mutation == "partition":
        groups = read_jsonl(folder / "clusters.semantic.jsonl")
        groups[0]["memberArticleIds"].remove("fx_en")
        rows(folder / "clusters.semantic.jsonl", groups)
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        dump(folder / "meta.json", meta | {"clustersSha256": sha256_file(folder / "clusters.semantic.jsonl")})
    else:
        neighbors = read_jsonl(folder / "neighbors.semantic.jsonl")
        neighbors[0]["neighbors"] = {"reference": [["missing", 0.9]], "duplicate": [["fx_en", 0.9], ["fx_en", 0.8]],
                                    "nan": [["fx_en", float("nan")]], "self": [["fx_sp", 0.9]]}[mutation]
        rows(folder / "neighbors.semantic.jsonl", neighbors)
        meta = json.loads((folder / "meta.neighbors.json").read_text(encoding="utf-8"))
        dump(folder / "meta.neighbors.json", meta | {"neighborsSha256": sha256_file(folder / "neighbors.semantic.jsonl")})
    corpus = load_corpus(settings)
    assert corpus.semantic_model is None and corpus.neighbors == {} and len(corpus.clusters) == 3
    assert any("rechazados" in note for note in corpus.notes)


def test_semantic_disable_or_absent_preserves_lexical_ranking(sample):
    settings, _ = sample
    disabled = load_corpus(replace(settings, semantic_enabled=False))
    absent = load_corpus(replace(settings, semantic_root=settings.semantic_root / "none"))
    assert disabled.clusters == absent.clusters and disabled.neighbors == absent.neighbors == {}
    client, _ = client_for(replace(settings, semantic_enabled=False))
    response = client.post("/api/v1/queries", json={"question": "restricciones calado Canal lago Gatún"}).json()
    assert response["retrieval"]["method"] == "bm25+rapidfuzz" and not response["retrieval"]["semanticExpansion"]
    assert {hit["evidenceId"] for hit in response["hits"]} == {"fx_sp"}


def test_rrf_uses_real_ranks_and_never_copies_literal_coverage():
    index = SearchIndex([Doc("sp", "articulo", "calado Canal lago Gatún"), Doc("en", "articulo", "Shipping restrictions imposed")],
                        neighbors={"sp": [("en", 0.9)]})
    hits, _, _ = index.search("calado Canal lago Gatún")
    by_id = {hit.doc.doc_id: hit for hit in hits}
    assert by_id["en"].rrf_score == pytest.approx(1 / 61)
    assert by_id["sp"].rrf_score == pytest.approx(1 / 61)
    assert by_id["en"].coverage == 0 and by_id["en"].matched == [] and by_id["en"].supported
    assert index.search("ajedrez Marte")[0] == []


def test_untrusted_or_weak_anchor_cannot_add_semantic_support():
    index = SearchIndex([Doc("untrusted", "articulo", "calado Canal lago Gatún", semantic_eligible=False),
                         Doc("neighbor", "articulo", "Shipping restrictions imposed")],
                        neighbors={"untrusted": [("neighbor", 0.9)]})
    hits, _, _ = index.search("calado Canal lago Gatún")
    assert [hit.doc.doc_id for hit in hits] == ["untrusted"] and hits[0].semantic_similarity is None
    weak = SearchIndex([Doc("sp", "articulo", "Canal"), Doc("en", "articulo", "Shipping restrictions imposed")],
                       neighbors={"sp": [("en", 0.9)]})
    assert all(hit.doc.doc_id != "en" for hit in weak.search("Canal Gatún sequía riesgo")[0])


def test_t05_cross_topics_es_en_keeps_sources_dates_and_possible_update(sample):
    settings, _ = sample
    corpus = load_corpus(replace(settings, semantic_enabled=False))
    spanish, english = corpus.articles["fx_sp"], corpus.articles["fx_en"]
    spanish.title = "Canal de Panamá habilita 32 tránsitos diarios y calado de 48 pies"
    english.title = "Panama Canal increases daily transits to 33 and maximum draft to 49 feet"
    candidates = cross_contradictions([spanish, english])
    assert {claim[0] for claim in numeric_claims(english.title)} == {"tránsitos diarios", "pies de calado"}
    assert len(candidates) == 2
    internal = detect_contradictions("same-event", [spanish, english], False)
    assert len(internal) == 2 and all(len(candidate.versions) == 2 for candidate in internal)
    for candidate in candidates:
        assert {version.evidence_id for version in candidate.versions} == {"fx_sp", "fx_en"}
        assert all(version.published_at and version.url for version in candidate.versions)
        assert "actualización" in candidate.description and "ACP" in candidate.pending_verification
    english.published_at = datetime(2020, 1, 1, tzinfo=UTC)
    assert cross_contradictions([spanish, english]) == []
    english.published_at = spanish.published_at
    english.title = "Suez Canal increases daily transits to 33 and maximum draft to 49 feet"
    assert cross_contradictions([spanish, english]) == []


def test_t05_query_and_topic_expose_both_cross_topic_versions(sample):
    settings, _ = sample
    articles = read_jsonl(settings.snapshot_dir / "articles.jsonl")
    articles[0]["title"] = "Canal de Panamá habilita 32 tránsitos diarios y calado de 48 pies"
    articles[1]["title"] = "Panama Canal increases daily transits to 33 and maximum draft to 49 feet"
    rows(settings.snapshot_dir / "articles.jsonl", articles)
    seal_snapshot(settings.snapshot_dir)
    client, service = client_for(replace(settings, semantic_enabled=False))
    response = client.post("/api/v1/queries", json={"question": "Canal Panamá tránsitos calado"}).json()
    assert response["answerStatus"] == "contradiccion" and len(response["contradictions"]) == 2
    assert {citation["evidenceId"] for citation in response["citations"]} >= {"fx_sp", "fx_en"}
    assert "48 pies" in response["answer"] and "49 feet" in response["answer"] and "2026-10-06" in response["answer"]
    tid = service.corpus.articles["fx_sp"].cluster_id
    detail = client.get(f"/api/v1/topics/{tid}").json()
    assert len(detail["contradictions"]) == 2 and detail["summary"]["hasContradictions"]


@pytest.mark.parametrize("public", [False, True])
def test_usgs_routes_magnitude_order_panama_time_citations_followup(sample, public):
    settings, _ = sample
    if public:
        settings = replace(settings, auth_mode="public", local_mode=False, persistence="none")
    client, service = client_for(settings)
    path = "/api/v1/public/queries" if public else "/api/v1/queries"
    extra = {"context": {"snapshotId": service.corpus.snapshot_id}} if public else {}
    response = client.post(path, json={"question": "mayores sismos USGS de 2024", **extra})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["intent"] == "eventos_sismicos" and data["answerStatus"] == "respondida"
    assert data["retrieval"]["method"] == "usgs-catalog"
    assert [hit["evidenceId"] for hit in data["hits"]] == ["fx_high", "fx_low"]
    assert "2024-04-02 20:30 (hora de Panamá)" in data["answer"] and "caja regional" in data["answer"] and "no prueban daños" in data["answer"]
    assert all(cite["url"].endswith(cite["evidenceId"]) for cite in data["citations"])
    assert {cite["field"] for cite in data["citations"]} == {"magnitude", "timePanama", "place", "depth"}
    followup = client.post(path, json={"question": "¿Cuáles son las fuentes?", "followUp": data["followUpContext"], **extra}).json()
    assert followup["answerStatus"] == "respondida" and {cite["evidenceId"] for cite in followup["citations"]} == {"fx_high", "fx_low"}
    year = client.post(path, json={"question": "¿Y en 2025?", "followUp": data["followUpContext"], **extra}).json()
    assert year["answerStatus"] == "abstencion" and year["citations"] == []


@pytest.mark.parametrize("question", ["sismos USGS de 2025", "sismos USGS hoy", "sismos USGS en Chile en 2024", "daños del sismo USGS de 2024"])
def test_usgs_unsupported_period_geography_or_damage_abstains(sample, question):
    client, _ = client_for(sample[0])
    response = client.post("/api/v1/queries", json={"question": question}).json()
    assert response["answerStatus"] == "abstencion" and response["citations"] == [] and response["missing"]


def test_usgs_panama_name_filter_does_not_assert_territory(sample):
    client, _ = client_for(sample[0])
    response = client.post("/api/v1/queries", json={"question": "sismos en Panamá de 2024"}).json()
    assert [hit["evidenceId"] for hit in response["hits"]] == ["fx_low"]
    assert "campo de ubicación" in response["answer"] and "no equivale al territorio" in response["answer"]


@pytest.mark.parametrize("tampering", ["hash", "url", "geometry"])
def test_usgs_corrupt_catalog_is_rejected(sample, tampering):
    settings, _ = sample
    path = settings.snapshot_dir / "events.geojson"
    data = json.loads(path.read_text(encoding="utf-8"))
    if tampering == "url":
        data["features"][0]["properties"]["url"] = "https://other.example/inventado"
    elif tampering == "geometry":
        data["features"][0]["geometry"]["coordinates"] = []
    else:
        data["features"][0]["properties"]["magnitude"] = 99
    dump(path, data)
    if tampering != "hash":
        seal_snapshot(settings.snapshot_dir)
    corpus = load_corpus(settings)
    assert corpus.events == {} and any("USGS rechazado" in note for note in corpus.notes)


def event_composition(pack, order):
    statements = []
    for eid in order:
        item = pack.items[eid]
        statements.append(ComposeStatement(text=f"USGS: M {item['magnitude']} · {item['place']} · {item['timePanama']}",
                          citations=[ComposeCitation(evidence_id=eid, field=field, passage=item[field]) for field in ("magnitude", "place", "timePanama")]))
    return ModelCompose(statements=statements)


def test_usgs_composition_validates_real_fields_and_rejects_unbacked_claims(sample):
    service = Services(sample[0])
    response = service.query("revision", QueryRequest(question="sismos USGS de 2024"))
    pack, order = pack_from_response(service.corpus, response)
    valid = event_composition(pack, order)
    assert validate_composition(valid, pack, order, QueryIntent.eventos_sismicos)[1] == []
    damages = valid.model_copy(deep=True)
    damages.statements[0].text += "; hubo daños"
    assert any("daños" in error for error in validate_composition(damages, pack, order, QueryIntent.eventos_sismicos)[1])
    invented = valid.model_copy(deep=True)
    invented.statements[0].text += "; M 9.9"
    assert any("9.9" in error and "cifra" in error.lower() for error in validate_composition(invented, pack, order, QueryIntent.eventos_sismicos)[1])
    reversed_order = valid.model_copy(deep=True)
    reversed_order.statements.reverse()
    assert any("orden" in error for error in validate_composition(reversed_order, pack, order, QueryIntent.eventos_sismicos)[1])


@pytest.mark.parametrize("public", [False, True])
def test_usgs_compose_route_preserves_scope_notes(sample, public):
    settings = replace(sample[0], offline=False)
    if public:
        settings = replace(settings, auth_mode="public", local_mode=False, persistence="none")
    client, service = client_for(settings)
    provider = FakeProvider(settings)

    def generate(system, user, *, schema):
        from umbral_api.providers import ProviderResult

        response = service.query("revision", QueryRequest(question="sismos USGS de 2024"))
        pack, order = pack_from_response(service.corpus, response)
        return ProviderResult(event_composition(pack, order), "fake-model")

    provider.generate = generate
    service.providers["gemini"] = provider
    if public:
        from .test_public import Counter

        service.public_gemini_counter = Counter()
    path = "/api/v1/public/queries/compose" if public else "/api/v1/queries/compose"
    extra = {"context": {"snapshotId": service.corpus.snapshot_id}} if public else {}
    response = client.post(path, json={"question": "sismos USGS de 2024", **extra}).json()
    assert response["answerMode"] == "modelo" and response["attempts"] == 1
    assert "caja regional" in response["response"]["answer"] and "no prueban daños" in response["response"]["answer"]
