import 'fake-indexeddb/auto';
import { IDBFactory } from 'fake-indexeddb';
import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CACHE_MAX_AGE_MS, CACHE_SCHEMA, indexedDbStore, latestAgendaUpdate, persistQueryCache, restoreQueryCache, type CacheStore } from './queryCache';

const memory = (initial: string | null = null): CacheStore & { value: string | null } => {
  const store = { value: initial, read: async () => store.value, write: async (next: string) => { store.value = next; } };
  return store;
};
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
const agenda = (filters: unknown, kind = 'live') => ['topics', filters, kind];

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

async function saved(source: QueryClient) {
  const store = memory();
  const stop = persistQueryCache(source, store, 10);
  return { store, stop };
}

it('guarda tras un retardo y restaura la agenda y el estado de la API real, como obsoletos y sin fichas', async () => {
  const a = client();
  const { store, stop } = await saved(a);
  a.setQueryData(agenda({ limit: 5 }), { items: [{ id: 't1' }], total: 1 });
  a.setQueryData(['topic', 't1', 'live'], { summary: { id: 't1' } });
  a.setQueryData(['health', 'live'], { snapshotId: 's1' });
  expect(store.value).toBeNull();
  await vi.advanceTimersByTimeAsync(20);
  expect(store.value).not.toBeNull();
  stop();

  const b = client();
  expect(await restoreQueryCache(b, store)).toBe(true);
  expect(b.getQueryData(agenda({ limit: 5 }))).toEqual({ items: [{ id: 't1' }], total: 1 });
  expect(b.getQueryData(['topic', 't1', 'live'])).toBeUndefined();
  expect(b.getQueryCache().find({ queryKey: agenda({ limit: 5 }) })?.state.isInvalidated).toBe(true);
  expect(b.getQueryData(['health', 'live'])).toEqual({ snapshotId: 's1' });
  expect(latestAgendaUpdate(b)).toBeGreaterThan(0);
});

it('no guarda datos de la API simulada, casos del usuario ni reglas', async () => {
  const a = client();
  const { store, stop } = await saved(a);
  a.setQueryData(agenda({ limit: 5 }, 'mock'), { items: [] });
  a.setQueryData(['workspace-cases'], [{ case: 'privado' }]);
  a.setQueryData(['rules', 'live'], { weights: {} });
  await vi.advanceTimersByTimeAsync(50);
  stop();
  expect(store.value).toBeNull();
});

it('descarta la copia si cambió el esquema, caducó o está dañada', async () => {
  const state = (schema: number, savedAt: number, updated = savedAt) => JSON.stringify({ schema, savedAt, state: { mutations: [], queries: [
    { queryKey: agenda({ limit: 5 }), queryHash: 'h', state: { data: { items: [] }, dataUpdatedAt: updated, status: 'success', dataUpdateCount: 1, errorUpdateCount: 0, error: null, errorUpdatedAt: 0, fetchFailureCount: 0, fetchFailureReason: null, fetchMeta: null, isInvalidated: false, fetchStatus: 'idle' } }] } });
  const now = Date.now();
  expect(await restoreQueryCache(client(), memory(state(CACHE_SCHEMA, now)), now)).toBe(true);
  expect(await restoreQueryCache(client(), memory(state(CACHE_SCHEMA + 1, now)), now)).toBe(false);
  expect(await restoreQueryCache(client(), memory(state(CACHE_SCHEMA, now - CACHE_MAX_AGE_MS - 1)), now)).toBe(false);
  expect(await restoreQueryCache(client(), memory(state(CACHE_SCHEMA, now, now - CACHE_MAX_AGE_MS - 1)), now)).toBe(false);
  expect(await restoreQueryCache(client(), memory('{no es json'), now)).toBe(false);
  expect(await restoreQueryCache(client(), memory(null), now)).toBe(false);
});

it('conserva solo las agendas más recientes', async () => {
  const a = client();
  const { store, stop } = await saved(a);
  for (let i = 0; i < 15; i++) { vi.setSystemTime(1_000_000 + i * 1000); a.setQueryData(agenda({ limit: i }), { i }); }
  await vi.advanceTimersByTimeAsync(20);
  stop();
  const b = client();
  await restoreQueryCache(b, store, Date.now());
  const kept = b.getQueryCache().findAll({ queryKey: ['topics'] }).map((query) => (query.state.data as { i: number }).i).sort((x, y) => x - y);
  expect(kept).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]);
});

it('un almacenamiento que falla deja la aplicación sin caché pero sin errores', async () => {
  const broken: CacheStore = { read: async () => { throw new Error('bloqueado'); }, write: async () => { throw new Error('cuota'); } };
  expect(await restoreQueryCache(client(), broken)).toBe(false);
  const a = client();
  const stop = persistQueryCache(a, broken, 5);
  a.setQueryData(agenda({ limit: 5 }), { items: [] });
  await vi.advanceTimersByTimeAsync(20);
  expect(() => stop()).not.toThrow();
});

it('el almacén IndexedDB guarda y lee un registro, y sin IndexedDB falla de forma controlada', async () => {
  vi.useRealTimers();
  const store = indexedDbStore(new IDBFactory());
  expect(await store.read()).toBeNull();
  await store.write('{"a":1}');
  expect(await store.read()).toBe('{"a":1}');
  vi.stubGlobal('indexedDB', undefined);
  try {
    await expect(indexedDbStore().read()).rejects.toThrow();
    expect(await restoreQueryCache(client(), indexedDbStore())).toBe(false);
  } finally { vi.unstubAllGlobals(); }
});
