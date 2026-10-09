import json

from umbral_pipeline import cli, refresh


def test_news_candidate_never_promotes_snapshot(monkeypatch, tmp_path):
    calls = {}
    candidate = tmp_path / "snapshots" / "20261008-candidate"

    def fake_daily(data_dir, **kwargs):
        calls["data_dir"] = data_dir
        calls.update(kwargs)
        return candidate

    monkeypatch.setattr(refresh, "run_daily", fake_daily)
    monkeypatch.setattr(refresh, "_require_calibrated_news_model", lambda: None)
    result = refresh.run_news_candidate(tmp_path, previous_dir=tmp_path / "previous",
                                        progress="progress", log="logger")

    assert result == candidate
    assert calls == {
        "data_dir": tmp_path,
        "previous_dir": tmp_path / "previous",
        "set_current": False,
        "sources": ("tvn", "tvn-sitemap", "gdelt", "bing-news", "usgs"),
        "progress": "progress",
        "log": "logger",
    }


def test_news_candidate_rejects_unprofiled_laya(monkeypatch):
    monkeypatch.delenv("UMBRAL_LAYA_MODEL_DIR", raising=False)
    monkeypatch.setattr(refresh, "load_profile", lambda *_args, **_kwargs: None)

    try:
        refresh._require_calibrated_news_model()
    except ValueError as exc:
        assert "calibración Laya" in str(exc)
    else:
        raise AssertionError("no se deben extraer titulares con un clasificador Laya sin calibración")


def test_news_candidate_requires_complete_calibrated_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("UMBRAL_LAYA_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(refresh, "resolve_model_version", lambda *_args, **_kwargs: "laya-ft-calibrated")
    monkeypatch.setattr(refresh, "load_profile", lambda *_args, **_kwargs: object())

    try:
        refresh._require_calibrated_news_model()
    except ValueError as exc:
        assert "artefacto calibrado completo" in str(exc)
    else:
        raise AssertionError("el checkpoint sin rl_agent_config.json no se puede cargar")


def test_news_candidate_cli_exposes_no_promotion_flag(monkeypatch, tmp_path, capsys):
    candidate = tmp_path / "snapshots" / "20261008-candidate"
    called = {}

    def fake_candidate(data_dir, **kwargs):
        called["data_dir"] = data_dir
        called.update(kwargs)
        return candidate

    monkeypatch.setattr(refresh, "run_news_candidate", fake_candidate)
    parsed = cli.build_parser().parse_args(["--data-dir", str(tmp_path), "news-candidate", "--json-progress"])
    assert not hasattr(parsed, "no_set_current")

    assert cli.main(["--data-dir", str(tmp_path), "news-candidate", "--json-progress"]) == 0
    assert called["data_dir"] == tmp_path
    assert called["previous_dir"] is None
    assert callable(called["progress"])
    assert json.loads(capsys.readouterr().out.strip()) == {
        "snapshotId": candidate.name,
        "path": str(candidate),
    }


def test_promote_news_accepts_only_verified_laya_candidate(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    candidate_id = "20261008-a1b2c3d4"
    candidate = snapshots / candidate_id
    candidate.mkdir()
    activated = []

    monkeypatch.setattr(refresh, "load_verified", lambda path: {
        "manifest": {"classifier": {"classifier": "laya"}, "cutoffUtc": "2026-10-08T10:00:00Z",
                     "queries": [{"source": "tvn_rss", "returned": 2}]},
        "quality": {"news": {"uniqueCanonicalUrls": 150, "tvnValid": 40, "newlyDiscovered": 2}},
    })
    monkeypatch.setattr(refresh, "activate_snapshot", activated.append)

    assert refresh.promote_news_candidate(tmp_path, candidate_id) == candidate
    assert activated == [candidate]


def test_promote_news_rejects_non_laya_snapshot(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "20261008-a1b2c3d4").mkdir()
    monkeypatch.setattr(refresh, "load_verified", lambda path: {
        "manifest": {"classifier": {"classifier": "baseline"}, "cutoffUtc": "2026-10-08T10:00:00Z",
                     "queries": [{"source": "tvn_rss", "returned": 2}]},
        "quality": {"news": {"uniqueCanonicalUrls": 150, "tvnValid": 40, "newlyDiscovered": 2}},
    })

    try:
        refresh.promote_news_candidate(tmp_path, "20261008-a1b2c3d4")
    except ValueError as exc:
        assert "Laya" in str(exc)
    else:
        raise AssertionError("un snapshot baseline no debe promoverse como candidato de noticias")


def test_promote_news_keeps_usable_candidate_when_optional_source_fails(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    candidate_id = "20261008-a1b2c3d4"
    (snapshots / candidate_id).mkdir()
    activated = []
    monkeypatch.setattr(refresh, "load_verified", lambda _path: {
        "manifest": {
            "classifier": {"classifier": "laya"},
            "cutoffUtc": "2026-10-08T10:00:00Z",
            "provisionalReasons": ["source_query_failures"],
            "queries": [{"source": "tvn_rss", "returned": 120},
                        {"source": "gdelt_doc", "returned": 0, "error": "HTTP 429"}],
        },
        "quality": {"news": {"uniqueCanonicalUrls": 150, "tvnValid": 40, "newlyDiscovered": 5}},
    })
    monkeypatch.setattr(refresh, "activate_snapshot", activated.append)

    assert refresh.promote_news_candidate(tmp_path, candidate_id) == snapshots / candidate_id
    assert activated == [snapshots / candidate_id]


def test_promote_news_rejects_degraded_candidate_below_coverage_minimum(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    candidate_id = "20261008-a1b2c3d4"
    (snapshots / candidate_id).mkdir()
    activated = []
    monkeypatch.setattr(refresh, "load_verified", lambda _path: {
        "manifest": {
            "classifier": {"classifier": "laya"}, "cutoffUtc": "2026-10-08T10:00:00Z",
            "provisionalReasons": ["source_query_failures"],
            "queries": [{"source": "tvn_rss", "returned": 2},
                        {"source": "gdelt_doc", "returned": 0, "error": "HTTP 429"}],
        },
        "quality": {"news": {"uniqueCanonicalUrls": 80, "tvnValid": 20, "newlyDiscovered": 5}},
    })
    monkeypatch.setattr(refresh, "activate_snapshot", activated.append)

    try:
        refresh.promote_news_candidate(tmp_path, candidate_id)
    except ValueError as exc:
        assert "Cobertura insuficiente" in str(exc)
    else:
        raise AssertionError("un candidato bajo el mínimo operativo no se debe promover")
    assert activated == []


def test_promote_news_rejects_candidate_without_new_headlines(monkeypatch, tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    candidate_id = "20261008-a1b2c3d4"
    (snapshots / candidate_id).mkdir()
    activated = []
    monkeypatch.setattr(refresh, "load_verified", lambda _path: {
        "manifest": {
            "classifier": {"classifier": "laya"}, "cutoffUtc": "2026-10-08T10:00:00Z",
            "queries": [{"source": "tvn_rss", "returned": 120}],
        },
        "quality": {"news": {"uniqueCanonicalUrls": 150, "tvnValid": 40, "newlyDiscovered": 0}},
    })
    monkeypatch.setattr(refresh, "activate_snapshot", activated.append)

    try:
        refresh.promote_news_candidate(tmp_path, candidate_id)
    except ValueError as exc:
        assert "titulares nuevos" in str(exc)
    else:
        raise AssertionError("no se debe promover un corte sin noticias nuevas")
    assert activated == []


def test_promote_news_cli_reports_source_failure_without_traceback(monkeypatch, tmp_path, capsys):
    def fail_promotion(*_args, **_kwargs):
        raise ValueError("fuentes fallidas")

    monkeypatch.setattr(refresh, "promote_news_candidate", fail_promotion)

    assert cli.main(["--data-dir", str(tmp_path), "promote-news", "20261008-a1b2c3d4"]) == 1
    error = capsys.readouterr().err
    assert error == "ERROR: fuentes fallidas\n"
