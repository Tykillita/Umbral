// Genera src/lib/api/schema.d.ts desde el contrato publicado por `backend`.
// Uso: pnpm gen:api   (usa ../api/openapi.json; override: OPENAPI_JSON=ruta)
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const input = resolve(root, process.env.OPENAPI_JSON ?? '../api/openapi.json');
const output = resolve(root, 'src/lib/api/schema.d.ts');
if (!existsSync(input)) {
  console.error(`No existe ${input}. Lo publica el agente backend (apps/api/openapi.json).`);
  process.exit(1);
}
const bin = resolve(root, 'node_modules/openapi-typescript/bin/cli.js');
const r = spawnSync(process.execPath, [bin, input, '-o', output], { stdio: 'inherit' });
process.exit(r.status ?? 1);
