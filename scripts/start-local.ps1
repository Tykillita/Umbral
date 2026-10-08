# Arranque local reproducible: compila el frontend (Node 24) y sirve todo desde FastAPI en :8000.
# Uso: scripts\start-local.ps1 [-Offline] [-Port 8000]
param([switch]$Offline, [ValidateRange(1024,65535)][int]$Port = 8000)
. "$PSScriptRoot\lib.ps1"
Need uv; Need npx
$env:PUBLIC_API_MODE = 'live'
$env:PUBLIC_AUTH_MODE = 'local'
$env:PUBLIC_API_URL = ''
$env:UMBRAL_LOCAL_MODE = '1'
$env:UMBRAL_AUTH_MODE = 'local'
$env:UMBRAL_PERSISTENCE = 'sqlite'
if ($Offline) { $env:UMBRAL_OFFLINE = '1' }
Pnpm-Web build
if ($Offline) {
    In-Dir 'apps/api' { uv run --offline uvicorn umbral_api.main:app --host 127.0.0.1 --port $Port }
} else {
    In-Dir 'apps/api' { uv run uvicorn umbral_api.main:app --host 127.0.0.1 --port $Port }
}
