# Desarrollo: API en :8000 y Astro dev en :4321 (dos procesos). Ctrl+C detiene el frontend y la API.
. "$PSScriptRoot\lib.ps1"
Need uv; Need npx
$api = Start-Process -PassThru -NoNewWindow -WorkingDirectory (Join-Path $Root 'apps/api') uv -ArgumentList 'run','uvicorn','umbral_api.main:app','--port','8000','--reload'
try { Pnpm-Web dev } finally { if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force } }
