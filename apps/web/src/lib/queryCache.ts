import { dehydrate, hydrate, type DehydratedState, type QueryClient } from '@tanstack/react-query';

/**
 * Copia local de los datos públicos de la última visita (agenda, estado y snapshot) para que la aplicación
 * muestre algo útil mientras el backend despierta. No guarda fichas, casos, borradores ni reglas (llevan el
 * trabajo editorial del navegador, que debe leerse siempre en vivo) y solo guarda respuestas de la API real.
 * Todo lo restaurado se marca como obsoleto: se muestra de inmediato pero siempre se vuelve a pedir.
 * Subir `CACHE_SCHEMA` al cambiar la forma de esas respuestas descarta las copias antiguas.
 */
export const CACHE_SCHEMA = 1;
export const CACHE_DB = 'umbral-cache-v1';
export const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const ROOTS = ['topics', 'health', 'snapshot'] as const;
const LIMITS: Record<string, number> = { topics: 12, health: 1, snapshot: 1 };
const SAVE_DELAY_MS = 1000;

export interface CacheStore { read(): Promise<string | null>; write(value: string): Promise<void> }
interface Stored { schema: number; savedAt: number; state: DehydratedState }

/** Un único registro en IndexedDB; cualquier fallo (modo privado, cuota) deja la aplicación sin caché, nunca rota. */
export function indexedDbStore(factory: IDBFactory | undefined = globalThis.indexedDB): CacheStore {
  let database: Promise<IDBDatabase> | null = null;
  const open = () => {
    if (!factory) return Promise.reject(new Error('IndexedDB no disponible'));
    database ??= new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(CACHE_DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore('cache');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('IndexedDB bloqueada'));
    }).catch((error: unknown) => { database = null; throw error; });
    return database;
  };
  return {
    async read() {
      const db = await open();
      return new Promise((resolve, reject) => {
        const request = db.transaction('cache', 'readonly').objectStore('cache').get('current');
        request.onsuccess = () => resolve(typeof request.result === 'string' ? request.result : null);
        request.onerror = () => reject(request.error);
      });
    },
    async write(value) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const transaction = db.transaction('cache', 'readwrite');
        transaction.objectStore('cache').put(value, 'current');
        transaction.oncomplete = () => resolve();
        transaction.onerror = transaction.onabort = () => reject(transaction.error);
      });
    },
  };
}

const root = (key: readonly unknown[]) => String(key[0]);
const cacheable = (key: readonly unknown[]) =>
  (ROOTS as readonly string[]).includes(root(key)) && key[key.length - 1] === 'live';

function snapshot(client: QueryClient): DehydratedState {
  const state = dehydrate(client, { shouldDehydrateQuery: (query) => query.state.status === 'success' && cacheable(query.queryKey) });
  const kept = new Map<string, number>();
  const queries = [...state.queries]
    .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt)
    .filter((query) => {
      const name = root(query.queryKey), count = (kept.get(name) ?? 0) + 1;
      kept.set(name, count);
      return count <= (LIMITS[name] ?? 0);
    });
  return { mutations: [], queries };
}

/** Carga la copia guardada en el cliente. Devuelve `true` si había datos vigentes. Nunca lanza. */
export async function restoreQueryCache(client: QueryClient, store: CacheStore = indexedDbStore(), now = Date.now()): Promise<boolean> {
  try {
    const raw = await store.read();
    if (!raw) return false;
    const stored = JSON.parse(raw) as Partial<Stored>;
    if (stored.schema !== CACHE_SCHEMA || typeof stored.savedAt !== 'number' || !stored.state || !Array.isArray(stored.state.queries)) return false;
    if (now - stored.savedAt > CACHE_MAX_AGE_MS || stored.savedAt > now + 60_000) return false;
    const queries = stored.state.queries.filter((query) => Array.isArray(query.queryKey) && cacheable(query.queryKey)
      && query.state?.status === 'success' && typeof query.state.dataUpdatedAt === 'number' && now - query.state.dataUpdatedAt <= CACHE_MAX_AGE_MS);
    if (!queries.length) return false;
    hydrate(client, { mutations: [], queries: queries.map((query) => ({ ...query, state: { ...query.state, isInvalidated: true } })) });
    return true;
  } catch {
    return false;
  }
}

/** Guarda la copia (con retardo) cada vez que cambian datos cacheables. Devuelve la función que lo detiene. */
export function persistQueryCache(client: QueryClient, store: CacheStore = indexedDbStore(), delayMs = SAVE_DELAY_MS): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let dirty = false;
  const flush = () => {
    if (timer) clearTimeout(timer);
    timer = undefined;
    if (!dirty) return;
    dirty = false;
    const state = snapshot(client);
    if (!state.queries.length) return;
    void store.write(JSON.stringify({ schema: CACHE_SCHEMA, savedAt: Date.now(), state } satisfies Stored)).catch(() => undefined);
  };
  const unsubscribe = client.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated' || event.action.type !== 'success' || !cacheable(event.query.queryKey)) return;
    dirty = true;
    timer ??= setTimeout(flush, delayMs);
  });
  const onHide = () => { if (document.visibilityState === 'hidden') flush(); };
  document.addEventListener('visibilitychange', onHide);
  window.addEventListener('pagehide', flush);
  return () => {
    unsubscribe();
    document.removeEventListener('visibilitychange', onHide);
    window.removeEventListener('pagehide', flush);
    flush();
  };
}

/** Marca de tiempo (ms) de la agenda guardada más reciente que sigue en la caché, o `null`. */
export function latestAgendaUpdate(client: QueryClient): number | null {
  const times = client.getQueryCache().findAll({ queryKey: ['topics'] }).map((query) => query.state.dataUpdatedAt).filter((time) => time > 0);
  return times.length ? Math.max(...times) : null;
}
