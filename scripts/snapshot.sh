#!/usr/bin/env bash
# Prepara el snapshot de datos en data/snapshots/.
#   scripts/snapshot.sh --fixture          snapshot 100% fixture SIN red (demo/CI; marcado provisional + containsFixtures)
#   scripts/snapshot.sh                    snapshot real: descarga TVN RSS + GDELT + Banco Mundial (~20 min por límites de GDELT), clasificador baseline
#   scripts/snapshot.sh --classifier laya  igual, con Laya local (requiere scripts/setup.sh --laya y pesos en caché HF)
source "$(dirname "$0")/lib.sh"
need uv
cd "$ROOT/pipeline"
if [[ "${1:-}" == "--fixture" ]]; then uv run python -m umbral_pipeline fixture-snapshot; exit $?; fi
ARGS=("$@"); [[ ${#ARGS[@]} -eq 0 ]] && ARGS=(--classifier baseline)
uv run python -m umbral_pipeline snapshot "${ARGS[@]}"
