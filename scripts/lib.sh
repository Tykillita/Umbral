#!/usr/bin/env bash
# Utilidades compartidas por los scripts bash. Se usa con: source "$(dirname "$0")/lib.sh"
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PNPM_VERSION="10.33.0"   # debe coincidir con "packageManager" de apps/web/package.json

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: falta '$1' en el PATH. Ver README.md (Requisitos)." >&2; exit 1; }; }

# pnpm sin instalarlo globalmente. apps/web declara 'node@24' como devDependency, así que los
# scripts de pnpm (astro, vitest...) corren con Node 24 aunque el Node global sea otro.
pnpm_web() {
  if [[ "${1:-}" != "install" && ! -d "$ROOT/apps/web/node_modules/.bin" ]]; then
    echo "ERROR: apps/web no tiene dependencias instaladas (falta node_modules/.bin). Ejecuta scripts/setup.sh." >&2; return 1
  fi
  (
    cd "$ROOT/apps/web"
    if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* ]]; then
      export npm_config_script_shell="$(cygpath -w "$(command -v bash)")"
      # pnpm puede conservar bin/node (placeholder) después del preinstall Windows.
      local node_shim="node_modules/.bin/node"
      if [[ -f "$node_shim" && -f node_modules/.pnpm/node@24.21.0/node_modules/node/bin/node.exe ]]; then
        sed -i 's|/node/bin/node"|/node/bin/node.exe"|g' "$node_shim"
      fi
    fi
    local npx_options=(-y)
    [[ "${UMBRAL_OFFLINE:-}" != 1 ]] || npx_options+=(--offline)
    npx "${npx_options[@]}" "pnpm@${PNPM_VERSION}" "$@"
  )
}
