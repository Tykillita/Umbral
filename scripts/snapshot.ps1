# Prepara el snapshot de datos en data/snapshots/.
#   scripts\snapshot.ps1 --fixture          snapshot 100% fixture SIN red (demo/CI; provisional + containsFixtures)
#   scripts\snapshot.ps1                    snapshot real: TVN RSS + GDELT + Banco Mundial (~20 min por límites de GDELT), baseline
#   scripts\snapshot.ps1 --classifier laya  con Laya local (requiere scripts\setup.ps1 -Laya y pesos en caché HF)
. "$PSScriptRoot\lib.ps1"
Need uv
if ($args.Count -gt 0 -and $args[0] -eq '--fixture') { In-Dir 'pipeline' { uv run python -m umbral_pipeline fixture-snapshot }; return }
$a = if ($args.Count -eq 0) { @('--classifier', 'baseline') } else { $args }
In-Dir 'pipeline' { uv run python -m umbral_pipeline snapshot @a }
