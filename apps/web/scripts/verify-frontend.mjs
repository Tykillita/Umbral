/** QA reproducible del frontend; conserva logs, comandos, fechas UTC y hashes en .qa/. */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = resolve(web, '..', '..');
const qa = join(web, '.qa');
if (Number(process.versions.node.split('.')[0]) !== 24) throw new Error('Ejecuta este script con el Node 24 incluido en apps/web.');
mkdirSync(qa, { recursive: true });
const hash = (value) => createHash('sha256').update(value).digest('hex');
const files = [];
function visit(directory) {
  for (const item of readdirSync(directory, { withFileTypes: true }).sort((a,b) => a.name.localeCompare(b.name))) {
    if (['node_modules','.astro','.qa','dist','dist-public'].includes(item.name)) continue;
    const path = join(directory, item.name);
    if (item.isDirectory()) visit(path);
    else if (/\.(?:ts|tsx|astro|css|mjs)$/.test(item.name) || ['package.json','pnpm-lock.yaml','README.md'].includes(item.name)) files.push(path);
  }
}
visit(web);
const sourceFiles = files.map((path) => ({ path: relative(web,path).replaceAll('\\','/'), sha256: hash(readFileSync(path)) }));
const receipt = { startedAt: new Date().toISOString(), finishedAt: null, sourceSha256: hash(JSON.stringify(sourceFiles)), sourceFiles,
  openapiSha256: hash(readFileSync(join(repo,'apps/api/openapi.json'))), commands: [], buildChecks: [], success: false };
function run(name, executable, args, overrides = {}) {
  const startedAt = new Date().toISOString();
  const result = spawnSync(executable, args, { cwd: web, env: { ...process.env, ASTRO_TELEMETRY_DISABLED: '1', ...overrides }, encoding: 'utf8', maxBuffer: 15 * 1024 * 1024, windowsHide: true });
  const output = (result.stdout ?? '') + (result.stderr ?? '') + (result.error ? '\n' + result.error.message : '');
  const log = name + '.log';
  writeFileSync(join(qa,log), output, 'utf8');
  process.stdout.write(output);
  receipt.commands.push({ name, command: [relative(repo,executable).replaceAll('\\','/'), ...args], startedAt, finishedAt: new Date().toISOString(), exitCode: result.status ?? 1, log, outputSha256: hash(output), environment: overrides });
  if (result.status !== 0) throw new Error(name + ' falló; revisa .qa/' + log);
}
try {
  run('astro-check', process.execPath, ['node_modules/astro/bin/astro.mjs','check']);
  run('vitest', process.execPath, ['node_modules/vitest/vitest.mjs','run']);
  const python = join(repo,'tests/.venv/Scripts/python.exe');
  run('no-native-static', python, [join(repo,'scripts/check_no_native_ui.py')]);
  run('build-public', process.execPath, ['node_modules/astro/bin/astro.mjs','build','--outDir','dist-public'], { PUBLIC_API_MODE: 'live', PUBLIC_AUTH_MODE: 'public', PUBLIC_API_URL: '' });
  run('build-local', process.execPath, ['node_modules/astro/bin/astro.mjs','build','--outDir','dist'], { PUBLIC_API_MODE: 'live', PUBLIC_AUTH_MODE: 'local', PUBLIC_API_URL: '' });
  for (const output of ['dist-public','dist']) {
    const directory = join(web,output);
    if (existsSync(join(directory,'brand/concepts')) || existsSync(join(directory,'brand/README.md'))) throw new Error('El build contiene fuentes de revisión de marca.');
    for (const file of ['index.html','app/index.html','brand/umbral-logo.png','favicon.ico']) if (!existsSync(join(directory,file))) throw new Error('Falta un recurso del build: ' + file);
    receipt.buildChecks.push({ directory: output, indexSha256: hash(readFileSync(join(directory,'app/index.html'))), excludedConcepts: true });
  }
  const publicJavaScript = readdirSync(join(web,'dist-public/_astro')).filter((file) => file.endsWith('.js')).map((file) => readFileSync(join(web,'dist-public/_astro',file),'utf8')).join('\n');
  if (/identitytoolkit\.googleapis\.com|securetoken\.googleapis\.com/.test(publicJavaScript)) throw new Error('La build pública incluye Firebase Auth.');
  if (!existsSync(join(web,'public/brand/concepts'))) throw new Error('Las fuentes de marca originales deben conservarse.');
  receipt.success = true;
} finally {
  receipt.finishedAt = new Date().toISOString();
  const finalFiles = sourceFiles.map((entry) => ({ ...entry, sha256: hash(readFileSync(join(web,entry.path))) }));
  receipt.sourcesUnchanged = JSON.stringify(sourceFiles) === JSON.stringify(finalFiles);
  writeFileSync(join(qa,'frontend-receipt.json'), JSON.stringify(receipt,null,2) + '\n', 'utf8');
  process.stdout.write('\nRecibo: apps/web/.qa/frontend-receipt.json\n');
}
