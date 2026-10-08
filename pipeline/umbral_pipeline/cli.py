"""CLI: uv run python -m umbral_pipeline <comando>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="umbral_pipeline", description="Pipeline de datos de Umbral")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="carpeta data/ (raw/ y snapshots/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="descarga fuentes y guarda crudo en data/raw/<runId>/")
    f.add_argument("--window-days", type=int, default=30)
    f.add_argument("--sources", default="tvn,gdelt,worldbank,usgs")
    f.add_argument("--gdelt-step-days", type=int, default=10)

    b = sub.add_parser("build", help="valida, clasifica, agrupa y exporta un snapshot desde un raw")
    b.add_argument("--raw", type=Path, default=None, help="carpeta raw (por defecto la mas reciente)")
    b.add_argument("--classifier", choices=["laya", "baseline"], default="baseline")
    b.add_argument("--extra-raw", type=Path, action="append", default=[], help="raws adicionales a fusionar (p. ej. ampliar la ventana)")
    b.add_argument("--fixtures", action="store_true", help="anade casos T01-T04 etiquetados fixture (el snapshot lo declara)")
    b.add_argument("--snapshot-version", default="1.0.0")
    b.add_argument("--no-set-current", action="store_true", help="no actualiza data/snapshots/CURRENT (snapshot candidato)")
    b.add_argument("--no-laya-tiebreak", action="store_true", help="desactiva el desempate Laya de duplicados ambiguos")

    s = sub.add_parser("snapshot", help="fetch + build en un paso")
    s.add_argument("--window-days", type=int, default=30)
    s.add_argument("--classifier", choices=["laya", "baseline"], default="baseline")
    s.add_argument("--fixtures", action="store_true")

    v = sub.add_parser("verify", help="verifica SHA-256, snapshotId y claves foraneas de un snapshot")
    v.add_argument("snapshot_dir", type=Path)

    for name, help_text in (("daily", "actualiza 30 días con ingesta incremental y Laya"),
                            ("reclassify", "reclasifica un snapshot normalizado con Laya, sin crudo")):
        refresh = sub.add_parser(name, help=help_text)
        refresh.add_argument("--previous", type=Path, default=None)
        refresh.add_argument("--classifier", choices=["laya"], default="laya")
        refresh.add_argument("--no-set-current", action="store_true")
        refresh.add_argument("--json-progress", action="store_true")
        if name == "daily":
            refresh.add_argument("--window-days", type=int, choices=[30], default=30)
            refresh.add_argument("--overlap-hours", type=int, choices=[48], default=48)
            refresh.add_argument("--raw", type=Path, default=None, help="ingesta ya descargada (pruebas/recuperación)")

    sub.add_parser("fixture-snapshot", help="snapshot 100% fixture (sin red) marcado provisional/fixture, para CI")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir: Path = args.data_dir

    if args.cmd == "fetch":
        from .fetch import run_fetch

        run_fetch(
            data_dir, window_days=args.window_days, sources=tuple(args.sources.split(",")),
            gdelt_window_days=args.gdelt_step_days,
        )
        return 0

    if args.cmd in ("build", "snapshot"):
        from .build import run_build

        raw = getattr(args, "raw", None)
        if args.cmd == "snapshot":
            from .fetch import run_fetch

            raw = run_fetch(data_dir, window_days=args.window_days)
        out = run_build(
            data_dir, raw_dir=raw, classifier=args.classifier,
            extra_raw=getattr(args, "extra_raw", []), use_fixtures=args.fixtures,
            laya_tiebreak=not getattr(args, "no_laya_tiebreak", False),
            set_current=not getattr(args, "no_set_current", False),
        )
        print(f"snapshot: {out}")
        return 0

    if args.cmd == "fixture-snapshot":
        from .build import run_build

        out = run_build(data_dir, raw_dir=None, classifier="baseline", use_fixtures=True, fixtures_only=True)
        print(f"snapshot: {out}")
        return 0

    if args.cmd == "verify":
        from .snapshot import verify_snapshot

        ok, problems = verify_snapshot(args.snapshot_dir)
        for pr in problems:
            print("ERROR:", pr)
        print("OK" if ok else "FALLO")
        return 0 if ok else 1
    if args.cmd in {"daily", "reclassify"}:
        import json

        from .refresh import run_daily, run_reclassify

        progress = (lambda stage, done, total: print(json.dumps({"stage": stage, "completed": done,
                                                                  "total": total}), flush=True)) if args.json_progress else None
        log = (lambda message: print(message, file=sys.stderr, flush=True)) if args.json_progress else print
        previous = args.previous
        if args.cmd == "reclassify":
            previous = previous or data_dir / "snapshots" / (data_dir / "snapshots" / "CURRENT").read_text().strip()
            out = run_reclassify(data_dir, previous, set_current=not args.no_set_current, progress=progress, log=log)
        else:
            out = run_daily(data_dir, previous_dir=previous, raw_dir=args.raw, set_current=not args.no_set_current,
                            progress=progress, log=log)
        print(json.dumps({"snapshotId": out.name, "path": str(out)}) if args.json_progress else f"snapshot: {out}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
