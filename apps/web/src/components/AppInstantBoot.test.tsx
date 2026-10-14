import 'fake-indexeddb/auto';
import { IDBFactory } from 'fake-indexeddb';
import { QueryClient } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import { MockApi } from '../lib/mock/mockApi';
import { chooseRole } from '../lib/session';
import { CACHE_SCHEMA, indexedDbStore, persistQueryCache } from '../lib/queryCache';
import type { TopicFilters } from '../lib/api/types';

const resolveApi = vi.hoisted(() => vi.fn());
vi.mock('../lib/api', () => ({ resolveApi }));
vi.mock('../lib/config', async (importOriginal) => {
  const original = await importOriginal<typeof import('../lib/config')>();
  return { ...original, config: { ...original.config, authMode: 'public', apiMode: 'live' } };
});
vi.mock('../lib/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/auth')>()),
  initAuth: vi.fn().mockResolvedValue({ mode: 'public', uid: null, error: null }),
  authState: () => ({ mode: 'public', uid: null, error: null }),
}));

const DEFAULT_FILTERS: TopicFilters = { q: '', category: '', evidence: '', band: '', reviewStatus: '', limit: 5, scope: 'in_scope', tvnGap: false };

/** MockApi que se declara «live» para compartir las claves de caché con la API real. */
function liveApi() {
  const api = new MockApi();
  Object.defineProperty(api, 'kind', { value: 'live' });
  return api;
}

/** Simula una visita anterior: deja la agenda de MockApi guardada en IndexedDB como lo haría la aplicación. */
async function seedPreviousVisit() {
  const client = new QueryClient();
  const stop = persistQueryCache(client, indexedDbStore(), 0);
  // El corte del mock es una fecha fija; la copia local descarta cortes de más de 36 h, así que se simula uno reciente.
  client.setQueryData(['topics', DEFAULT_FILTERS, 'live'], { ...(await liveApi().topics(DEFAULT_FILTERS)), cutoffUtc: new Date().toISOString() });
  await new Promise((resolve) => setTimeout(resolve, 30));
  stop();
  expect(CACHE_SCHEMA).toBeGreaterThan(0);
}

beforeAll(() => {
  Object.defineProperty(window, 'scrollTo', { value: vi.fn(), configurable: true });
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true });
  Object.defineProperty(window, 'matchMedia', {
    value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    configurable: true,
  });
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
beforeEach(() => {
  localStorage.clear();
  window.location.hash = '#/agenda';
  globalThis.indexedDB = new IDBFactory();
  resolveApi.mockReset();
  chooseRole('editor', null);
});
afterEach(cleanup);

it('con datos de la última visita pinta la agenda guardada mientras el servidor despierta y luego se actualiza', async () => {
  await seedPreviousVisit();
  let finish!: (value: unknown) => void;
  resolveApi.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  render(<App />);

  expect((await screen.findAllByTestId('topic-card')).length).toBeGreaterThan(0);
  expect(screen.getByTestId('nav-agenda')).toBeTruthy();
  expect(screen.getByTestId('boot-notice').textContent).toContain('datos guardados');
  expect(screen.queryByTestId('app-loading')).toBeNull();
  expect(screen.queryByTestId('snapshot-badge')).toBeNull();

  finish({ api: liveApi(), reason: null });
  await waitFor(() => expect(screen.queryByTestId('boot-notice')).toBeNull());
  await waitFor(() => expect(screen.getByTestId('snapshot-badge')).toBeTruthy());
  expect(screen.getAllByTestId('topic-card').length).toBeGreaterThan(0);
});

it('sin datos previos pinta toda la aplicación con esqueletos y el aviso de progreso, sin pantalla bloqueante', async () => {
  resolveApi.mockImplementation((progress: (value: unknown) => void) => {
    progress({ attempt: 3, elapsedMs: 9000, message: 'Seguimos intentando la conexión…' });
    return new Promise(() => {});
  });
  render(<App />);

  expect(await screen.findByTestId('agenda-skeleton')).toBeTruthy();
  expect(screen.getAllByTestId('skeleton-card')).toHaveLength(5);
  expect(screen.getByTestId('agenda-search')).toBeTruthy();
  expect(screen.getByTestId('boot-notice').textContent).toMatch(/Despertando el servidor/);
  await waitFor(() => expect(screen.getByTestId('boot-notice').textContent).toContain('Intento 3 · 9 s'));
  expect(screen.queryByTestId('app-loading')).toBeNull();
});

it('si el arranque falla conserva los datos guardados y ofrece reintentar', async () => {
  await seedPreviousVisit();
  resolveApi.mockRejectedValueOnce(new Error('El servicio está iniciando.'));
  resolveApi.mockImplementation(() => new Promise(() => {}));
  render(<App />);

  const error = await screen.findByTestId('app-boot-error');
  expect(error.textContent).toContain('El servicio está iniciando.');
  expect(screen.getAllByTestId('topic-card').length).toBeGreaterThan(0);
  expect(screen.getAllByRole('alert')).toHaveLength(1);

  fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
  await waitFor(() => expect(resolveApi).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByTestId('app-boot-error')).toBeNull());
  expect(screen.getByTestId('boot-notice')).toBeTruthy();
});
