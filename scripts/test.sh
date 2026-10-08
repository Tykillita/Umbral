#!/usr/bin/env bash
# Corre todas las pruebas. Uso: scripts/test.sh [rapido|todo]   (rapido omite Playwright; por defecto: todo)
source "$(dirname "$0")/lib.sh"
need uv; need npx
MODE="${1:-todo}"; RC=0
run() { echo; echo "### $*"; if ! "$@"; then RC=1; fi; }
run_in() { local dir="$1"; shift; (cd "$ROOT/$dir" && "$@"); }
run uv run --no-project python "$ROOT/scripts/check_repo.py"
run uv run --no-project python "$ROOT/scripts/check_no_native_ui.py"
run run_in apps/api uv run ruff check .
run run_in apps/api uv run mypy src
run run_in apps/api uv run pytest
run run_in apps/api uv run python scripts/export_openapi.py --check
run run_in pipeline uv run ruff check .
run run_in pipeline uv run pytest
run pnpm_web check
run pnpm_web test
export UMBRAL_TESTS_STRICT=1
if [[ "$MODE" != "rapido" ]]; then
  export PUBLIC_API_MODE=live PUBLIC_API_URL='' PUBLIC_AUTH_MODE=local
  run pnpm_web build
  export PUBLIC_AUTH_MODE=public
  run pnpm_web exec astro build --outDir dist-public
  export PUBLIC_AUTH_MODE=local
  run run_in tests uv run --frozen --extra e2e pytest -ra
else
  run run_in tests uv run --frozen pytest integration -ra
fi
[[ $RC -eq 0 ]] && echo "TODO OK" || echo "HAY FALLOS (ver arriba)"
exit $RC
