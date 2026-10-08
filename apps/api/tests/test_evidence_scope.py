"""E y estado de evidencia: una serie oficial vinculada por palabra clave es contexto, no fuente primaria."""

from __future__ import annotations

from .conftest import find_topic

API = "/api/v1"


def comp(detail, key):
    return next(c for c in detail["score"]["components"] if c["key"] == key)


def test_keyword_linked_official_series_does_not_raise_e_or_status(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'inflación')}").json()
    assert d["officialContext"]["indicators"]  # la serie se sigue mostrando como contexto oficial
    assert d["evidence"]["officialContextLinked"] is True and d["evidence"]["primarySourceLinked"] is False
    assert comp(d, "E")["value"] == 0.33  # una procedencia
    assert d["evidence"]["status"] == "insuficiente"
    assert any("solo contexto" in g["message"] for g in d["evidence"]["gaps"] if g["code"] == "sin_fuente_primaria")
    # el impacto automático no suma «serie oficial vinculada»
    assert "serie oficial" not in d["impact"]["justification"]


def test_two_provenances_without_confirmed_primary_is_partial_and_e_067(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'calado')}").json()
    assert d["evidence"]["independentProvenances"] == 2
    assert comp(d, "E")["value"] == 0.67 and d["evidence"]["status"] == "parcial"
    assert any("solo contexto" in lim or "confirmada" in lim for lim in comp(d, "E")["limits"])


def test_reviewer_confirmed_primary_source_raises_e_to_1_and_status_with_reason(make_app):
    c = make_app()
    tid = find_topic(c, "calado")
    case = c.get(f"{API}/cases/case-{tid}").json()
    body = {"expectedVersion": case["version"], "status": "en_revision", "reviewer": "Marta", "primarySourceConfirmed": True}
    r = c.patch(f"{API}/cases/{case['caseId']}/review", json=body)
    assert r.status_code == 422 and "comentario" in r.json()["message"]  # exige motivo
    r = c.patch(f"{API}/cases/{case['caseId']}/review", json={**body, "comment": "Comunicado ACP del 6/10 confirma el calado."})
    assert r.status_code == 200
    cv = r.json()
    assert cv["primarySourceConfirmed"] is True and cv["primarySourceConfirmedBy"] == "Marta" and "ACP" in cv["primarySourceReason"]
    d = c.get(f"{API}/topics/{tid}").json()
    assert comp(d, "E")["value"] == 1 and d["evidence"]["primarySourceLinked"] is True
    assert d["evidence"]["status"] == "suficiente" and d["score"]["total"] > 96.6
    assert not any(g["code"] == "sin_fuente_primaria" for g in d["evidence"]["gaps"])
    # es por usuario: otro usuario sigue viendo el estado del sistema
    other = c.get(f"{API}/topics/{tid}", headers={"X-Umbral-User": "beto"}).json()
    assert comp(other, "E")["value"] == 0.67 and other["evidence"]["status"] == "parcial"
    # el revisor puede retirarla
    back = c.patch(f"{API}/cases/{cv['caseId']}/review", json={"expectedVersion": cv["version"], "status": "requiere_evidencia",
                                                              "reviewer": "Marta", "comment": "Retiro.", "primarySourceConfirmed": False})
    assert back.status_code == 200 and comp(c.get(f"{API}/topics/{tid}").json(), "E")["value"] == 0.67


def test_sponsored_content_is_flagged_and_limited(make_app):
    c = make_app()
    tid = find_topic(c, "internet móvil")
    d = c.get(f"{API}/topics/{tid}").json()
    assert d["summary"]["possibleSponsored"] and d["evidence"]["possibleSponsored"]
    assert d["articles"][0]["sponsoredContent"] is True
    assert any("patrocinado" in w for w in d["warnings"]) and any(g["code"] == "contenido_patrocinado" for g in d["evidence"]["gaps"])
    e = comp(d, "E")
    assert e["value"] <= 0.33 and d["evidence"]["status"] == "insuficiente"
    # ni siquiera la confirmación de un revisor lo eleva por encima de 0,33
    case = d["case"]
    c.patch(f"{API}/cases/{case['caseId']}/review", json={"expectedVersion": 0, "status": "en_revision", "reviewer": "M",
                                                         "primarySourceConfirmed": True, "comment": "x"})
    assert comp(c.get(f"{API}/topics/{tid}").json(), "E")["value"] <= 0.33


def test_impact_category_needs_corroboration_not_series(make_app):
    c = make_app()
    d = c.get(f"{API}/topics/{find_topic(c, 'puerto de balboa')}").json()  # logística con 2 procedencias
    assert "con evidencia que lo corrobora" in d["impact"]["justification"] and "de 3 factores" in d["impact"]["justification"]
