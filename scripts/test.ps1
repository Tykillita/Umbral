# Corre todas las pruebas. Uso: scripts\test.ps1 [-Rapido]   (-Rapido omite build y Playwright)
param([switch]$Rapido)
. "$PSScriptRoot\lib.ps1"
Need uv; Need npx
$script:rc = 0
function Step([string]$name, [scriptblock]$b) {
    Write-Host "`n### $name"
    try { & $b; if ($LASTEXITCODE -ne 0) { $script:rc = 1 } } catch { Write-Host $_; $script:rc = 1 }
}
Step 'higiene' { uv run --no-project python (Join-Path $Root 'scripts/check_repo.py') }
Step 'regla nada nativo' { uv run --no-project python (Join-Path $Root 'scripts/check_no_native_ui.py') }
Step 'api ruff'      { In-Dir 'apps/api' { uv run ruff check . } }
Step 'api mypy'      { In-Dir 'apps/api' { uv run mypy src } }
Step 'api pytest'    { In-Dir 'apps/api' { uv run pytest } }
Step 'api OpenAPI'   { In-Dir 'apps/api' { uv run python scripts/export_openapi.py --check } }
Step 'pipeline ruff' { In-Dir 'pipeline' { uv run ruff check . } }
Step 'pipeline pytest' { In-Dir 'pipeline' { uv run pytest } }
Step 'web check' { Pnpm-Web check }
Step 'web test'  { Pnpm-Web test }
$env:UMBRAL_TESTS_STRICT = '1'
if (-not $Rapido) {
    $env:PUBLIC_API_MODE='live'; $env:PUBLIC_API_URL=''; $env:PUBLIC_AUTH_MODE='local'
    Step 'web build local' { Pnpm-Web build }
    $env:PUBLIC_AUTH_MODE='public'
    Step 'web build público' { Pnpm-Web exec astro build --outDir dist-public }
    $env:PUBLIC_AUTH_MODE='local'
    Step 'integración y E2E' { In-Dir 'tests' { uv run --frozen --extra e2e pytest -ra } }
} else {
    Step 'integración' { In-Dir 'tests' { uv run --frozen pytest integration -ra } }
}
if ($script:rc -eq 0) { Write-Host 'TODO OK' } else { Write-Host 'HAY FALLOS (ver arriba)' }
exit $script:rc
