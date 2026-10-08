#!/usr/bin/env bash
# Desarrollo: API en :8000 y Astro dev en :4321 (dos procesos). Ctrl+C detiene ambos.
source "$(dirname "$0")/lib.sh"
need uv; need npx
(cd "$ROOT/apps/api" && uv run uvicorn umbral_api.main:app --port 8000 --reload) & API=$!
trap 'kill $API 2>/dev/null || true' EXIT
pnpm_web dev
