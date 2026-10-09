# API y web de captura con SQLite desechable, sin proveedores ni credenciales personales.
param([int]$Port = 8876, [string]$Python = '')
$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$work = Join-Path $root '.production/video-work'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$env:PYTHONPATH = Join-Path $root 'apps/api/src'
$env:UMBRAL_OFFLINE = '1'
$env:UMBRAL_AUTH_MODE = 'local'
$env:UMBRAL_LOCAL_MODE = '1'
$env:UMBRAL_PERSISTENCE = 'sqlite'
$env:UMBRAL_ALLOW_FIXTURE = '0'
$env:UMBRAL_STRICT_INTEGRITY = '1'
$env:UMBRAL_SQLITE_PATH = Join-Path $work "capture-$([guid]::NewGuid()).sqlite"
$env:UMBRAL_WEB_DIST = Join-Path $root 'apps/web/dist'
$env:CHATGPT_TOKEN_FILE = Join-Path $work 'no-token'
$env:CHATGPT_CREDENTIALS_FILE = Join-Path $work 'no-credentials'
$env:CLAUDE_CLI = 'not-configured'
$env:GEMINI_API_KEY = ''
$env:NOTION_API_KEY = ''
Set-Location $root
if ($Python) {
    & $Python -m uvicorn umbral_api.main:app --host 127.0.0.1 --port $Port
} else {
    uv run --project apps/api --offline uvicorn umbral_api.main:app --host 127.0.0.1 --port $Port
}
