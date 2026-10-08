# Instala dependencias de api, pipeline y web. Uso: scripts\setup.ps1 [-Laya]
#   -Laya  instala además el extra opcional de Laya (PyTorch + pesos; descarga pesada, solo local).
param([switch]$Laya)
. "$PSScriptRoot\lib.ps1"
Need uv; Need node; Need npx
Write-Host '== API (apps/api) =='; In-Dir 'apps/api' { uv sync --frozen }
Write-Host '== Pipeline (pipeline) =='
if ($Laya) { In-Dir 'pipeline' { uv sync --frozen --extra laya } } else { In-Dir 'pipeline' { uv sync --frozen } }
Write-Host '== Web (apps/web) =='
if (-not (Test-Path (Join-Path $Root 'apps/web/pnpm-lock.yaml'))) { throw 'Falta apps/web/pnpm-lock.yaml; restaura el lockfile antes de instalar.' }
Pnpm-Web install --frozen-lockfile
Write-Host '== Pruebas de integración (tests) =='; In-Dir 'tests' { uv sync --frozen --extra e2e }
Write-Host 'Listo. Siguiente: scripts\snapshot.ps1 y scripts\start-local.ps1'
