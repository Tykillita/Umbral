# Utilidades compartidas por los scripts PowerShell. Se usa con: . "$PSScriptRoot\lib.ps1"
$ErrorActionPreference = 'Stop'
$script:Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:PnpmVersion = '10.33.0'   # debe coincidir con "packageManager" de apps/web/package.json

function Need([string]$cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Falta '$cmd' en el PATH. Ver README.md (Requisitos)." }
}
# pnpm sin instalarlo globalmente. apps/web declara 'node@24' como devDependency, así que los
# scripts de pnpm (astro, vitest...) corren con Node 24 aunque el Node global sea otro.
function Pnpm-Web {
    if ($args[0] -ne 'install' -and -not (Test-Path (Join-Path $script:Root 'apps/web/node_modules/.bin'))) {
        throw 'apps/web no tiene dependencias instaladas (falta node_modules/.bin). Ejecuta scripts\setup.ps1.'
    }
    # node's Windows preinstall cambia bin/node a bin/node.exe. pnpm puede conservar
    # el shim POSIX anterior tras añadir paquetes; reparar solo ese destino local.
    $nodeShim = Join-Path $script:Root 'apps/web/node_modules/.bin/node'
    $nodeExe = Join-Path $script:Root 'apps/web/node_modules/.pnpm/node@24.21.0/node_modules/node/bin/node.exe'
    if (($IsWindows -or $env:OS -eq 'Windows_NT') -and (Test-Path -LiteralPath $nodeExe) -and (Test-Path -LiteralPath $nodeShim)) {
        $shimText = [System.IO.File]::ReadAllText($nodeShim)
        $repaired = $shimText.Replace('/node/bin/node"', '/node/bin/node.exe"')
        if ($repaired -ne $shimText) { [System.IO.File]::WriteAllText($nodeShim, $repaired, [System.Text.UTF8Encoding]::new($false)) }
    }
    # pnpm utiliza `-c` al lanzar scripts. Un .npmrc del usuario con cmd.exe
    # no acepta ese argumento; Git Bash queda limitado a esta llamada.
    $previousShell = $env:npm_config_script_shell
    if ($IsWindows -or $env:OS -eq 'Windows_NT') {
        $gitBash = Join-Path $env:ProgramFiles 'Git/bin/bash.exe'
        if (-not (Test-Path -LiteralPath $gitBash)) {
            throw 'Falta Git Bash. Instala Git para Windows o usa bash con scripts/*.sh.'
        }
        $env:npm_config_script_shell = $gitBash
    }
    Push-Location (Join-Path $script:Root 'apps/web')
    try {
        $npxOptions = @('-y')
        if ($env:UMBRAL_OFFLINE -eq '1') { $npxOptions += '--offline' }
        $npxCommand = if ($IsWindows -or $env:OS -eq 'Windows_NT') { 'npx.cmd' } else { 'npx' }
        & $npxCommand @npxOptions "pnpm@$($script:PnpmVersion)" @args
        if ($LASTEXITCODE -ne 0) { throw "pnpm falló ($LASTEXITCODE)" }
    }
    finally { Pop-Location; $env:npm_config_script_shell = $previousShell }
}
function In-Dir([string]$dir, [scriptblock]$block) {
    Push-Location (Join-Path $script:Root $dir)
    try { & $block; if ($LASTEXITCODE -ne 0) { throw "falló en $dir ($LASTEXITCODE)" } }
    finally { Pop-Location }
}
