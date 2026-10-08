# Compila el frontend (Node 24 vía devDependency de apps/web). Las variables PUBLIC_* del entorno se embeben en el bundle.
. "$PSScriptRoot\lib.ps1"
Need npx
Pnpm-Web install --frozen-lockfile
Pnpm-Web build
