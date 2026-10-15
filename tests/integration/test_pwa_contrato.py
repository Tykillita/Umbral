"""Contrato estático de la PWA: se comprueba sobre los ficheros fuente, sin navegador ni red (la prueba E2E cubre el comportamiento)."""
from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
PUBLIC = WEB / "public"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} no es un PNG"
    return struct.unpack(">II", data[16:24])


class PwaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))

    def test_el_manifest_es_instalable(self) -> None:
        m = self.manifest
        self.assertEqual((m["display"], m["start_url"], m["scope"], m["lang"]), ("standalone", "/app", "/", "es"))
        self.assertTrue(m["name"] and m["short_name"])
        purposes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= purposes)

    def test_los_iconos_existen_y_miden_lo_que_declaran(self) -> None:
        for icon in self.manifest["icons"]:
            width, height = (int(n) for n in icon["sizes"].split("x"))
            self.assertEqual(png_size(PUBLIC / icon["src"].lstrip("/")), (width, height), icon["src"])
        self.assertEqual(png_size(PUBLIC / "brand" / "apple-touch-icon.png"), (180, 180))

    def test_la_cabecera_declara_manifest_viewport_e_ios(self) -> None:
        base = (WEB / "src" / "layouts" / "Base.astro").read_text(encoding="utf-8")
        for needle in (
            'rel="manifest" href="/manifest.webmanifest"', "viewport-fit=cover", "interactive-widget=resizes-content",
            'name="apple-mobile-web-app-capable"', 'rel="apple-touch-icon"', 'name="theme-color"',
        ):
            self.assertIn(needle, base)

    def test_el_service_worker_lleva_version_y_nunca_cachea_la_api(self) -> None:
        sw = (PUBLIC / "sw.js").read_text(encoding="utf-8")
        self.assertIn("__BUILD_VERSION__", sw)  # `astro.config.mjs` la sustituye en cada compilación
        self.assertIn("SKIP_WAITING", sw)  # una versión nueva no se activa sola
        self.assertRegex(sw, r"startsWith\('/api/'\)")
        self.assertIn("__PRECACHE_URLS__", sw)  # la lista la genera la compilación a partir de `dist`, que no contiene la API


if __name__ == "__main__":
    unittest.main()
