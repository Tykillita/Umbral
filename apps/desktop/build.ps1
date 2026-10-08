param([switch]$Installer, [switch]$SkipWeb)
$ErrorActionPreference = 'Stop'
$desktopDirectory = $PSScriptRoot
$repositoryDirectory = (Resolve-Path (Join-Path $desktopDirectory '../..')).Path
$nodeExecutable = Join-Path $repositoryDirectory 'apps/web/node_modules/node/bin/node.exe'
if (!(Test-Path -LiteralPath $nodeExecutable)) { throw 'Instala las dependencias de apps/web; se requiere su Node 24 local.' }
Push-Location $desktopDirectory
try {
  uv sync --locked
  if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar el runtime de escritorio.' }
  if (!$SkipWeb) {
    $env:PUBLIC_API_MODE='live'; $env:PUBLIC_API_URL=''; $env:PUBLIC_AUTH_MODE='local'; $env:ASTRO_TELEMETRY_DISABLED='1'
    Push-Location (Join-Path $repositoryDirectory 'apps/web')
    try { & $nodeExecutable node_modules/astro/bin/astro.mjs build --outDir ../desktop/staging/web }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'La web de escritorio no compiló.' }
  }
  & ./.venv/Scripts/python.exe stage.py
  if ($LASTEXITCODE -ne 0) { throw 'No se pudieron verificar los recursos.' }
  & ./.venv/Scripts/python.exe -m PyInstaller --noconfirm sidecar.spec
  if ($LASTEXITCODE -ne 0) { throw 'No se pudo empaquetar el motor local.' }
  $targetArgument = if ($Installer) { 'nsis' } else { '--dir' }
  & $nodeExecutable node_modules/electron-builder/cli.js --win $targetArgument --x64 --publish never
  if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar la aplicación Windows.' }
  Get-ChildItem -LiteralPath release -Filter '*.exe' | ForEach-Object {
    Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
  }
} finally { Pop-Location }
