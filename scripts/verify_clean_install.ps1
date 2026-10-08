# Revalida la instalación limpia: copia el repo SIN entornos, builds ni resultados a una carpeta temporal,
# ejecuta scripts\setup.ps1 (lockfiles congelados), pruebas rápidas, build y arranque offline, y guarda un recibo.
# Uso: scripts\verify_clean_install.ps1 [-Port 8191]
param([ValidateRange(1024,65535)][int]$Port = 8191)
$ErrorActionPreference = 'Stop'
$src = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$scratch = Join-Path $env:TEMP ("umbral-clean-" + (Get-Date -Format 'yyyyMMddTHHmmss'))
$sw = [Diagnostics.Stopwatch]::StartNew()
$steps = [ordered]@{}
function Step([string]$name, [scriptblock]$b) {
    $t = [Diagnostics.Stopwatch]::StartNew()
    & $b
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "falló: $name ($LASTEXITCODE)" }
    $steps[$name] = [math]::Round($t.Elapsed.TotalSeconds, 1)
}
$exclDirs = @('.git','.venv','node_modules','dist','.astro','.pytest_cache','.pytest_tmp','.pytest-tmp','.ruff_cache','.mypy_cache','__pycache__','.results','.umbral-local','.browsers','.qa','.firebase','playwright-report','test-results','raw')
$lock = @('apps/api/uv.lock','pipeline/uv.lock','tests/uv.lock','apps/web/pnpm-lock.yaml')
$locksBefore = @{}; foreach ($l in $lock) { $locksBefore[$l] = (Get-FileHash (Join-Path $src $l) -Algorithm SHA256).Hash.ToLower() }
robocopy $src $scratch /E /XD $exclDirs /XF .env .env.* *.sqlite* /NFL /NDL /NJH /NJS /NP | Out-Null
if (-not (Test-Path (Join-Path $scratch 'data/snapshots/CURRENT'))) { throw 'la copia no trae data/snapshots/CURRENT' }
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $src 'tests/.browsers'   # Chromium reutilizado de la caché (no se descarga de nuevo)
Push-Location $scratch
try {
    Step 'setup' { & (Join-Path $scratch 'scripts/setup.ps1') }
    Step 'higiene' { uv run --no-project python scripts/check_repo.py --strict }
    Step 'api: ruff+pytest' { Push-Location apps/api; try { uv run ruff check .; uv run pytest -q -p no:cacheprovider } finally { Pop-Location } }
    Step 'pipeline: ruff+pytest' { Push-Location pipeline; try { uv run ruff check .; uv run pytest -q -p no:cacheprovider } finally { Pop-Location } }
    Step 'web: check+test+build' { & (Join-Path $scratch 'scripts/build-web.ps1') }
    $env:UMBRAL_SQLITE_PATH = Join-Path $scratch 'clean.sqlite'
    $proc = Start-Process -PassThru -WindowStyle Hidden powershell -ArgumentList '-NoProfile','-File',(Join-Path $scratch 'scripts/start-local.ps1'),'-Offline','-Port',$Port
    $health = $null
    for ($i = 0; $i -lt 150 -and -not $health; $i++) {
        Start-Sleep 2
        try { $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 3 } catch { }
    }
    if (-not $health) { throw 'el servidor offline no respondió' }
    $steps['arranque offline (incluye build)'] = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    $homeHttp = (Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 10).StatusCode
    $locksAfter = @{}; foreach ($l in $lock) { $locksAfter[$l] = (Get-FileHash (Join-Path $scratch $l) -Algorithm SHA256).Hash.ToLower() }
    $same = $true; foreach ($l in $lock) { if ($locksBefore[$l] -ne $locksAfter[$l]) { $same = $false } }
    $receipt = [ordered]@{
        status = 'passed'; completedAtUtc = (Get-Date).ToUniversalTime().ToString('s') + 'Z'
        scratch = $scratch; totalSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 1); stepsSeconds = $steps
        health = @{ status = $health.status; apiVersion = $health.apiVersion; snapshotId = $health.snapshotId; offline = $health.offline; articles = $health.counts.articles; manifestVerified = $health.integrity.manifestVerified; predictionsHashVerified = $health.integrity.predictionsHashVerified }
        homeHttp = $homeHttp; locksUnchanged = $same; locksBefore = $locksBefore; locksAfter = $locksAfter
        note = 'Copia sin entornos ni resultados; dependencias con lockfiles congelados; Chromium reutilizado de la caché; no incluye el extra Laya.'
    }
    $receipt | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $src 'tests/.results/clean-install-final.json')
    Write-Host ("OK instalación limpia: {0}s, snapshot {1}, locks sin cambios: {2}" -f $receipt.totalSeconds, $health.snapshotId, $same)
}
finally {
    if ($proc) { taskkill /PID $proc.Id /T /F 2>&1 | Out-Null }
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | ForEach-Object { taskkill /PID $_.OwningProcess /T /F 2>&1 | Out-Null }
    Pop-Location
    Remove-Item Env:UMBRAL_SQLITE_PATH -ErrorAction SilentlyContinue
}
