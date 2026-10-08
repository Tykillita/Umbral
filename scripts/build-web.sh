#!/usr/bin/env bash
# Compila el frontend (Node 24 vía devDependency de apps/web). Las variables PUBLIC_* del entorno se embeben en el bundle.
source "$(dirname "$0")/lib.sh"
need npx
pnpm_web install --frozen-lockfile
pnpm_web build
