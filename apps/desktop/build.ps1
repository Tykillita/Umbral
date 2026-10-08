param([switch]$Installer, [switch]$Publish, [switch]$SkipWeb, [string]$Snapshot, [string]$Model)
$ErrorActionPreference = 'Stop'
if ($Publish -and !$Installer) { throw 'La publicación solo se permite junto al instalador NSIS.' }
if ($Publish -and !$env:GH_TOKEN) { throw 'La publicación requiere el token temporal GH_TOKEN de GitHub Actions.' }
$desktopDirectory = $PSScriptRoot
$repositoryDirectory = (Resolve-Path (Join-Path $desktopDirectory '../..')).Path
$nodeExecutable = Join-Path $repositoryDirectory 'apps/web/node_modules/node/bin/node.exe'
if (!(Test-Path -LiteralPath $nodeExecutable)) { throw 'Instala las dependencias de apps/web; se requiere su Node 24 local.' }
function Resolve-ProjectInput([string]$CandidatePath) {
  if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
    return (Resolve-Path -LiteralPath $CandidatePath).Path
  }
  return (Resolve-Path -LiteralPath (Join-Path $repositoryDirectory $CandidatePath)).Path
}
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
  $stageArguments = @()
  if ($Snapshot) { $stageArguments += @('--snapshot', (Resolve-ProjectInput $Snapshot)) }
  if ($Model) { $stageArguments += @('--model', (Resolve-ProjectInput $Model)) }
  & ./.venv/Scripts/python.exe stage.py @stageArguments
  if ($LASTEXITCODE -ne 0) { throw 'No se pudieron verificar los recursos.' }
  & ./.venv/Scripts/python.exe -m PyInstaller --noconfirm sidecar.spec
  if ($LASTEXITCODE -ne 0) { throw 'No se pudo empaquetar el motor local.' }
  $targetArgument = if ($Installer) { 'nsis' } else { '--dir' }
  $publishMode = if ($Publish) { 'always' } else { 'never' }
  & $nodeExecutable node_modules/electron-builder/cli.js --win $targetArgument --x64 --publish $publishMode
  if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar la aplicación Windows.' }
  Get-ChildItem -LiteralPath release -Filter '*.exe' | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$($_.FullName).sha256" -Value "$hash  $($_.Name)" -Encoding ascii -NoNewline
    [pscustomobject]@{ Path = $_.Name; SHA256 = $hash }
  }
} finally { Pop-Location }
