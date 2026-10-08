"""Evaluation CLI provenance controls and supplementary public metadata parsing."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from umbral_pipeline.ingest.tvn_sitemap import parse_news_sitemap

ROOT = Path(__file__).resolve().parents[2]


def test_sitemap_keeps_publication_title_only_and_never_uses_lastmod():
    xml = '''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
        <url><loc>https://www.tvn-2.com/nacionales/ejemplo</loc><lastmod>2026-10-07T00:00:00Z</lastmod>
        <news:news><news:publication><news:language>es</news:language></news:publication>
        <news:title>Titular de una prueba sintética</news:title><news:publication_date>2026-09-09T12:00:00Z</news:publication_date></news:news>
        <image:image><image:loc>https://image.example/private.jpg</image:loc></image:image></url>
        <url><loc>https://www.tvn-2.com/otro</loc><lastmod>2026-10-07T00:00:00Z</lastmod>
        <news:news><news:title>Sin publicación declarada</news:title></news:news></url></urlset>'''
    rows = parse_news_sitemap(xml)
    assert rows[0]["publishedRaw"] == "2026-09-09T12:00:00Z"
    assert rows[1]["publishedRaw"] is None
    assert rows[0]["publishedAtBasis"] == "news_sitemap_publication"
    assert all("image" not in str(row) and "lastmod" not in row for row in rows)


def test_evaluation_clis_against_analytic_synthetic_controls(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    spec = importlib.util.spec_from_file_location("verify_eval_tools", ROOT / "eval/verify_eval_tools.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    report = module.verify(ROOT / "pipeline/.pytest_cache" / f"eval-control-{uuid.uuid4().hex}")
    assert report["status"] == "passed"
    assert report["evaluationKind"] == "synthetic_control"
    assert len(report["checks"]) == 7
