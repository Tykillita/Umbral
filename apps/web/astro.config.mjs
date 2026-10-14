import { createHash } from 'node:crypto';
import { readdir, readFile, rm, realpath, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, dirname, sep } from 'node:path';
// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

// Salida estática (dist/) servible por FastAPI en local y por Firebase Hosting.
// En desarrollo, /api se reenvía a la API en localhost:8000 (override: UMBRAL_API_PROXY).
const apiProxy = process.env.UMBRAL_API_PROXY ?? 'http://localhost:8000';

/** @type {import('astro').AstroIntegration} */
const releaseAssets = {
  name: 'umbral-release-assets',
  hooks: {
    'astro:build:done': async ({ dir }) => {
      const root = await realpath(fileURLToPath(dir));
      for (const relative of ['brand/concepts', 'brand/README.md']) {
        const target = resolve(root, relative);
        if (!target.startsWith(root + sep)) throw new Error('El recurso de revisión sale del directorio de build.');
        let parent;
        try { parent = await realpath(dirname(target)); } catch (error) { if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') continue; throw error; }
        if (parent !== root && !parent.startsWith(root + sep)) throw new Error('Un enlace del build apunta fuera del directorio de salida.');
        await rm(target, { recursive: relative === 'brand/concepts', force: true });
      }
    },
  },
};

/** Lista recursivamente los archivos de `dir` como rutas web (con `/` inicial). */
async function listFiles(dir, prefix = '') {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) found.push(...await listFiles(resolve(dir, entry.name), `${prefix}/${entry.name}`));
    else found.push(`${prefix}/${entry.name}`);
  }
  return found;
}

/**
 * Sustituye en dist/sw.js la versión del build y la lista de recursos a precachear (todo `/_astro/*`, que lleva hash en
 * el nombre, más los iconos). La versión cambia si cambia cualquier recurso o el HTML; así el navegador detecta la
 * actualización y el aviso «Hay una versión nueva» aparece solo cuando hay algo nuevo de verdad.
 * @type {import('astro').AstroIntegration}
 */
const pwaBuild = {
  name: 'umbral-pwa',
  hooks: {
    'astro:build:done': async ({ dir }) => {
      const root = fileURLToPath(dir);
      const worker = resolve(root, 'sw.js');
      let source;
      try { source = await readFile(worker, 'utf8'); } catch (error) { if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') return; throw error; }
      const assets = (await listFiles(resolve(root, '_astro'), '/_astro').catch(() => []));
      const fixed = ['/manifest.webmanifest', '/favicon.svg', '/brand/icon-192.png', '/brand/icon-512.png', '/brand/icon-maskable-512.png', '/brand/apple-touch-icon.png'];
      const precache = [...assets, ...fixed].sort();
      const hash = createHash('sha256');
      for (const url of precache) hash.update(url);
      for (const page of ['index.html', 'app/index.html']) hash.update(await readFile(resolve(root, page)).catch(() => ''));
      const version = hash.digest('hex').slice(0, 12);
      const versionMarker = "const BUILD_VERSION = '__BUILD_VERSION__';";
      const precacheMarker = "const PRECACHE_URLS = JSON.parse('__PRECACHE_URLS__');";
      if (!source.includes(versionMarker) || !source.includes(precacheMarker)) throw new Error('sw.js perdió sus marcadores de versión y precaché.');
      // Funciones como reemplazo: así `$` en el texto no se interpreta como patrón.
      await writeFile(worker, source
        .replace(versionMarker, () => `const BUILD_VERSION = '${version}';`)
        .replace(precacheMarker, () => `const PRECACHE_URLS = ${JSON.stringify(precache)};`));
    },
  },
};

export default defineConfig({
  output: 'static',
  integrations: [react(), releaseAssets, pwaBuild],
  server: { port: 4321, host: 'localhost' },
  vite: {
    plugins: [tailwindcss()],
    server: {
      proxy: {
        '/api': { target: apiProxy, changeOrigin: true },
      },
    },
    preview: {
      proxy: {
        '/api': { target: apiProxy, changeOrigin: true },
      },
    },
  },
});
