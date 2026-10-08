#!/usr/bin/env bash
# Arranque local reproducible: compila el frontend (Node 24) y sirve todo desde FastAPI en :8000.
# Uso: scripts/start-local.sh [--offline] [--port 8000]
source "$(dirname "$0")/lib.sh"
need uv; need npx
export PUBLIC_API_MODE=live PUBLIC_AUTH_MODE=local PUBLIC_API_URL=''
export UMBRAL_LOCAL_MODE=1 UMBRAL_AUTH_MODE=local UMBRAL_PERSISTENCE=sqlite
PORT=8000
while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline) export UMBRAL_OFFLINE=1; shift ;;
    --port) [[ $# -ge 2 ]] || { echo "Falta valor de --port" >&2; exit 2; }; PORT="$2"; shift 2 ;;
    *) echo "Uso: scripts/start-local.sh [--offline] [--port 8000]" >&2; exit 2 ;;
  esac
done
[[ "$PORT" =~ ^[0-9]{4,5}$ && "$PORT" -ge 1024 && "$PORT" -le 65535 ]] || { echo "Puerto inválido (1024–65535)" >&2; exit 2; }
pnpm_web build
cd "$ROOT/apps/api"
uv_options=()
[[ "${UMBRAL_OFFLINE:-}" != 1 ]] || uv_options+=(--offline)
uv run "${uv_options[@]}" uvicorn umbral_api.main:app --host 127.0.0.1 --port "$PORT"
