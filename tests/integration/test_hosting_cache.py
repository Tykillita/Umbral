"""Hosting: las páginas HTML sin extensión (`/`, `/app`, `/jurado/...`) no se guardan en el navegador entre despliegues."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "apps" / "web" / "src" / "pages"


class HostingCacheTests(unittest.TestCase):
    def headers(self) -> dict[str, dict[str, str]]:
        rules = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))["hosting"]["headers"]
        return {rule["source"]: {h["key"]: h["value"] for h in rule["headers"]} for rule in rules}

    def test_las_paginas_sin_extension_llevan_no_cache(self) -> None:
        # cleanUrls sirve `/app` sin `.html`: la regla `**/*.html` no las cubre y Firebase aplicaría max-age=3600.
        headers = self.headers()
        source = next((s for s in headers if s.startswith("{") and "/app" in s), None)
        self.assertIsNotNone(source, "falta la regla para / y /app")
        self.assertEqual(headers[source]["Cache-Control"], "no-cache")
        parts = source.strip("{}").split(",")
        for route in ("/", "/app", "/app/**", "/jurado/**"):
            self.assertIn(route, parts)
        self.assertTrue((PAGES / "app.astro").exists() and (PAGES / "index.astro").exists())
        self.assertTrue((PAGES / "jurado").is_dir())

    def test_el_service_worker_y_el_manifest_no_se_guardan(self) -> None:
        headers = self.headers()
        self.assertIn("no-store", headers["/sw.js"]["Cache-Control"])
        self.assertEqual(headers["/manifest.webmanifest"]["Cache-Control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
