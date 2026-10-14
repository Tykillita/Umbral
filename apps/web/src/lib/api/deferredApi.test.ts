import { expect, it, vi } from 'vitest';
import { ApiError, type UmbralApi } from './client';
import { createDeferredApi } from './deferredApi';

const real = (overrides: Record<string, unknown> = {}) => ({ kind: 'live', health: vi.fn(async () => ({ snapshotId: 's1' })), topics: vi.fn(async (filters: unknown) => ({ filters })), connectorOverview: vi.fn(), ...overrides }) as unknown as UmbralApi;

it('las llamadas esperan a la API real y luego delegan con sus argumentos', async () => {
  const deferred = createDeferredApi('browser');
  let settled = false;
  const pending = deferred.api.topics({ limit: 5 } as never).then((value) => { settled = true; return value; });
  await Promise.resolve();
  expect(settled).toBe(false);
  const api = real();
  deferred.resolve(api);
  expect(await pending).toEqual({ filters: { limit: 5 } });
  expect(api.topics).toHaveBeenCalledWith({ limit: 5 });
  expect(await deferred.api.health()).toEqual({ snapshotId: 's1' });
});

it('si el arranque falla, las consultas fallan con ese error y las nuevas también', async () => {
  const deferred = createDeferredApi();
  const first = deferred.api.health();
  deferred.reject(new ApiError(503, { code: 'servicio', message: 'Sin servicio' }));
  await expect(first).rejects.toMatchObject({ status: 503 });
  await expect(deferred.api.topics({} as never)).rejects.toMatchObject({ status: 503 });
});

it('declara kind live y modo de espacio, y oculta los métodos opcionales hasta tener la API real', () => {
  const deferred = createDeferredApi('browser');
  expect(deferred.api.kind).toBe('live');
  expect(deferred.api.workspaceMode).toBe('browser');
  expect(deferred.api.connectorOverview).toBeUndefined();
  expect(deferred.api.exportWorkspace).toBeUndefined();
  expect(deferred.api.subscribe).toBeUndefined();
  expect(createDeferredApi().api.workspaceMode).toBeUndefined();
});

it('mantiene la identidad de cada método para no reiniciar efectos de React', () => {
  const { api } = createDeferredApi();
  expect(api.topics).toBe(api.topics);
});
