import { rm, realpath } from 'node:fs/promises';
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

export default defineConfig({
  output: 'static',
  integrations: [react(), releaseAssets],
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
