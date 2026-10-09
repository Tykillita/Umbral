param([switch]$Installer, [switch]$Publish, [switch]$SkipWeb, [string]$Snapshot, [string]$Model,
      [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
if ($Publish -and !$Installer) { throw 'La publicación solo se permite junto al instalador NSIS.' }
if ($Publish -and !$env:GH_TOKEN) { throw 'La publicación requiere el token temporal GH_TOKEN de GitHub Actions.' }
if ($Publish -and $OutputDirectory) { throw 'La publicación usa la carpeta release configurada por el proyecto.' }
$desktopDirectory = $PSScriptRoot
$repositoryDirectory = (Resolve-Path (Join-Path $desktopDirectory '../..')).Path
$nodeExecutable = Join-Path $repositoryDirectory 'apps/web/node_modules/node/bin/node.exe'
if (!(Test-Path -LiteralPath $nodeExecutable)) {
  $nodeStore = Join-Path $repositoryDirectory 'apps/web/node_modules/.pnpm'
  $nodeExecutable = Get-ChildItem -LiteralPath $nodeStore -Directory -Filter 'node@24*' -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'node_modules/node/node_modules/node-win-x64/bin/node.exe' } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
}
if (!(Test-Path -LiteralPath $nodeExecutable)) { throw 'Instala las dependencias de apps/web; se requiere su Node 24 local.' }
$nodeVersion = & $nodeExecutable --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v24\.') { throw 'El empaquetado requiere el Node 24 local de apps/web.' }
function Resolve-ProjectInput([string]$CandidatePath) {
  if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
    return (Resolve-Path -LiteralPath $CandidatePath).Path
  }
  return (Resolve-Path -LiteralPath (Join-Path $repositoryDirectory $CandidatePath)).Path
}
function Resolve-SafeOutputDirectory([string]$CandidatePath) {
  $scratchRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryDirectory '.production')).TrimEnd('\')
  $resolved = if ([System.IO.Path]::IsPathRooted($CandidatePath)) {
    [System.IO.Path]::GetFullPath($CandidatePath)
  } else {
    [System.IO.Path]::GetFullPath((Join-Path $repositoryDirectory $CandidatePath))
  }
  $prefix = $scratchRoot + [System.IO.Path]::DirectorySeparatorChar
  if (!$resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDirectory solo puede apuntar a una carpeta nueva dentro de .production.'
  }
  if (Test-Path -LiteralPath $resolved) { throw 'OutputDirectory ya existe; usa un destino nuevo dentro de .production.' }
  return $resolved
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
  $electronBuilderArguments = @('--win', $targetArgument, '--x64', '--publish', $publishMode)
  $artifactDirectory = Join-Path $desktopDirectory 'release'
  if ($OutputDirectory) {
    $artifactDirectory = Resolve-SafeOutputDirectory $OutputDirectory
    $electronBuilderArguments += @('--config.directories.output', $artifactDirectory)
  }
  & $nodeExecutable node_modules/electron-builder/cli.js @electronBuilderArguments
  if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar la aplicación Windows.' }
  $artifactFiles = if ($Installer) {
    Get-ChildItem -LiteralPath $artifactDirectory -Filter '*.exe' -File
  } else {
    Get-ChildItem -LiteralPath (Join-Path $artifactDirectory 'win-unpacked') -Filter '*.exe' -File
  }
  $artifactFiles | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$($_.FullName).sha256" -Value "$hash  $($_.Name)" -Encoding ascii -NoNewline
    [pscustomobject]@{ Path = $_.Name; SHA256 = $hash }
  }
} finally { Pop-Location }
