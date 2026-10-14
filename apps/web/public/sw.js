/* Service worker de Umbral: la app abre sin conexión y no sirve JS/CSS viejos tras un despliegue.
 *
 * - Las dos constantes con marcador (versión y lista de precaché) las sustituye el hook `umbral-pwa` de astro.config.mjs al terminar el build.
 * - La API NUNCA se cachea: ni `/api/` del mismo origen ni ninguna petición a otro origen (Render, proveedores de IA…).
 *   Así no quedan en caché tokens, cuentas, borradores ni respuestas del asistente.
 * - HTML: red primero (siempre la versión desplegada), con la copia local solo si no hay red.
 * - `/_astro/*` (nombres con hash) y el shell: caché primero.
 * - Datos estáticos (`/data/*`, `/public-config.json`): red primero con copia local para lectura sin conexión.
 * - Una versión nueva se instala en segundo plano y NO se activa sola: espera el mensaje SKIP_WAITING que envía el
 *   aviso «Hay una versión nueva» cuando la persona pulsa Actualizar.
 */
const BUILD_VERSION = '__BUILD_VERSION__';
const PRECACHE_URLS = JSON.parse('__PRECACHE_URLS__');
const APP_CACHE = `umbral-app-${BUILD_VERSION}`;
const DATA_CACHE = 'umbral-data-v1';
const DATA_CACHE_MAX_ENTRIES = 60;
const HTML_PAGES = ['/', '/app'];
const NAVIGATION_TIMEOUT_MS = 4000;
// El servidor responde `Vary: Origin` (CORS) y los <script type="module"> envían `Origin`; sin esto la copia guardada
// al precachear (sin Origin) no coincidiría y la app no abriría sin conexión.
const MATCH_OPTIONS = { ignoreVary: true };

/** Guarda una copia limpia (no "redirected") de una página; así se puede devolver a una navegación sin error. */
async function cachePage(cache, path) {
  const response = await fetch(path, { cache: 'reload', credentials: 'same-origin' });
  if (!response.ok) return;
  const body = await response.blob();
  const headers = new Headers(response.headers);
  const clean = () => new Response(body, { status: 200, headers });
  await cache.put(path, clean());
  const finalPath = new URL(response.url).pathname;
  if (finalPath !== path) await cache.put(finalPath, clean());
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);
    await cache.addAll(PRECACHE_URLS);
    // Las páginas se intentan guardar, pero que falle una no impide instalar (los recursos ya están).
    await Promise.allSettled(HTML_PAGES.map((path) => cachePage(cache, path)));
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('umbral-app-') && name !== APP_CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
  if (event.data && event.data.type === 'GET_VERSION' && event.source) event.source.postMessage({ type: 'VERSION', version: BUILD_VERSION });
});

function isCacheable(response) {
  return response && response.ok && response.status === 200 && response.type === 'basic' && !response.redirected;
}

async function trimDataCache(cache) {
  const keys = await cache.keys();
  for (let index = 0; index < keys.length - DATA_CACHE_MAX_ENTRIES; index += 1) await cache.delete(keys[index]);
}

async function networkFirst(request, cacheName, { timeoutMs = 0, fallbacks = [] } = {}) {
  const cache = await caches.open(cacheName);
  const requestUrl = new URL(request.url);
  // Los datos dependen de la consulta (?snapshot=…); las páginas no (la parte tras # ni siquiera llega al worker).
  const key = cacheName === DATA_CACHE ? requestUrl.pathname + requestUrl.search : requestUrl.pathname;
  const network = fetch(request).then(async (response) => {
    if (isCacheable(response)) {
      await cache.put(key, response.clone());
      if (cacheName === DATA_CACHE) await trimDataCache(cache);
    }
    return response;
  });
  network.catch(() => undefined); // si la copia local gana la carrera, un fallo posterior de red no debe quedar sin atender
  const cached = async () => {
    for (const path of [key, ...fallbacks]) {
      const hit = await cache.match(path, MATCH_OPTIONS) ?? await caches.match(path, MATCH_OPTIONS);
      if (hit) return hit;
    }
    return undefined;
  };
  try {
    if (!timeoutMs) return await network;
    // Con red lenta se prefiere la copia local; si no la hay, se espera a la red.
    const slow = new Promise((resolve) => setTimeout(resolve, timeoutMs, 'timeout'));
    const first = await Promise.race([network, slow]);
    if (first !== 'timeout') return first;
    return (await cached()) ?? await network;
  } catch (error) {
    const hit = await cached();
    if (hit) return hit;
    throw error;
  }
}

async function cacheFirst(request) {
  const hit = await caches.match(request, MATCH_OPTIONS);
  if (hit) return hit;
  const response = await fetch(request);
  if (isCacheable(response)) {
    const cache = await caches.open(APP_CACHE);
    await cache.put(request, response.clone());
  }
  return response;
}

function navigationFallbacks(path) {
  const alternate = path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : `${path}/`;
  const base = path.startsWith('/app') ? ['/app', '/app/'] : ['/'];
  return [alternate, ...base];
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  // Otro origen (API remota, proveedores) y la API del mismo origen: siempre directos a la red, nunca a la caché.
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/api') return;
  if (url.pathname === '/sw.js') return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, APP_CACHE, { timeoutMs: NAVIGATION_TIMEOUT_MS, fallbacks: navigationFallbacks(url.pathname) }));
    return;
  }
  if (url.pathname.startsWith('/_astro/') || url.pathname.startsWith('/brand/') || url.pathname === '/manifest.webmanifest') {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (url.pathname.startsWith('/data/') || url.pathname === '/public-config.json') {
    event.respondWith(networkFirst(request, DATA_CACHE));
  }
});
