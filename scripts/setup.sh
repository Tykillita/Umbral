#!/usr/bin/env bash
# Instala dependencias de api, pipeline y web. Uso: scripts/setup.sh [--laya]
#   --laya  instala además el extra opcional de Laya (PyTorch + pesos; descarga pesada, solo local).
source "$(dirname "$0")/lib.sh"
need uv; need node; need npx
echo "== API (apps/api) =="; (cd "$ROOT/apps/api" && uv sync --frozen)
echo "== Pipeline (pipeline) =="
if [[ "${1:-}" == "--laya" ]]; then (cd "$ROOT/pipeline" && uv sync --frozen --extra laya); else (cd "$ROOT/pipeline" && uv sync --frozen); fi
echo "== Web (apps/web) =="
[[ -f "$ROOT/apps/web/pnpm-lock.yaml" ]] || { echo "Falta apps/web/pnpm-lock.yaml; restaura el lockfile antes de instalar." >&2; exit 1; }
pnpm_web install --frozen-lockfile
echo "== Pruebas de integración (tests) =="; (cd "$ROOT/tests" && uv sync --frozen --extra e2e)
echo "Listo. Siguiente: scripts/snapshot.sh y scripts/start-local.sh"
