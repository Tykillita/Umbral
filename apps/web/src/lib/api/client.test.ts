import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpApi } from './client';
import { MOCK_HEALTH } from '../mock/data';
vi.mock('../auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../auth')>();
  return { ...actual, getConnectorAuthToken: vi.fn().mockResolvedValue('firebase-anonymous-test-token') };
});
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); delete window.umbralDesktop; });
describe('inicio del servicio público', () => {
  it('reintenta un arranque en frío con estado y sin token hasta estar listo', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json({},503)).mockResolvedValueOnce(json({},502)).mockResolvedValue(json(MOCK_HEALTH));
    vi.stubGlobal('fetch', fetch);
    const progress = vi.fn(), request = new HttpApi('', async () => null).waitUntilReady(progress);
    await vi.advanceTimersByTimeAsync(6000);
    expect(await request).toEqual(MOCK_HEALTH); expect(fetch).toHaveBeenCalledTimes(3);
    expect(progress).toHaveBeenLastCalledWith(expect.objectContaining({ attempt: 3, elapsedMs: 6000 }));
    expect(fetch.mock.calls[0]?.[1].headers.Authorization).toBeUndefined();
  });
  it('agota el presupuesto de 90s sin seguir intentando', async () => {
    const fetch = vi.fn().mockResolvedValue(json({},503)); vi.stubGlobal('fetch', fetch);
    const outcome = new HttpApi('', async () => null).waitUntilReady().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(90_000);
    expect(await outcome).toMatchObject({ code: 'inicio_agotado' });
    const count = fetch.mock.calls.length; await vi.advanceTimersByTimeAsync(60_000); expect(fetch).toHaveBeenCalledTimes(count);
  });
  it('una página HTML o JSON corrupto muestra el error y no pasa a mock', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('<html>Hosting</html>', { headers: { 'Content-Type': 'text/html' } })); vi.stubGlobal('fetch', fetch);
    await expect(new HttpApi('', async () => null).waitUntilReady()).rejects.toMatchObject({ code: 'respuesta_no_json' });
    expect(fetch).toHaveBeenCalledTimes(1);
    fetch.mockResolvedValue(new Response('{ broken', { headers: { 'Content-Type': 'application/json' } }));
    await expect(new HttpApi('', async () => null).health()).rejects.toMatchObject({ code: 'json_invalido' });
  });
  it('cancela una espera al desmontar el arranque', async () => {
    const fetch = vi.fn().mockResolvedValue(json({},503)); vi.stubGlobal('fetch', fetch);
    const controller = new AbortController(), outcome = new HttpApi('', async () => null).waitUntilReady(undefined, controller.signal).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(0); controller.abort();
    expect(await outcome).toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(90000); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('el backend de escritorio recibe su secreto efímero solamente en el header dedicado', async () => {
    window.umbralDesktop = { apiToken: 'ephemeral-test' } as typeof window.umbralDesktop;
    const fetch = vi.fn().mockResolvedValue(json(MOCK_HEALTH)); vi.stubGlobal('fetch', fetch);
    await new HttpApi('', async () => null).health();
    expect(fetch.mock.calls[0]?.[1].headers).toMatchObject({ 'x-umbral-desktop-token': 'ephemeral-test' });
    expect(fetch.mock.calls[0]?.[0]).not.toContain('ephemeral-test');
  });
});

  it('el secreto de escritorio no se envía a API remota ni viaja por redirecciones', async () => {
  window.umbralDesktop = { apiToken: 'ephemeral-test' } as typeof window.umbralDesktop;
  const fetch = vi.fn().mockResolvedValue(json(MOCK_HEALTH)); vi.stubGlobal('fetch', fetch);
  await new HttpApi('https://umbral-api.onrender.com', async () => null).health();
  expect(fetch.mock.calls[0]?.[1].headers['x-umbral-desktop-token']).toBeUndefined();
  expect(fetch.mock.calls[0]?.[1].redirect).toBe('error');
});

it('el escritorio enruta los conectores por IPC sin exponer el token de Firebase en fetch', async () => {
  const requestConnector = vi.fn().mockResolvedValue({ status: 200, body: { providers: {}, slackNotifications: {} }, retryAfter: null });
  window.umbralDesktop = { apiToken: 'ephemeral-test', requestConnector } as unknown as typeof window.umbralDesktop;
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  await expect(new HttpApi('', async () => null).connectorOverview()).resolves.toMatchObject({ providers: {}, slackNotifications: {} });
  expect(requestConnector).toHaveBeenCalledWith({ path: '/connectors', method: 'GET', body: undefined, token: 'firebase-anonymous-test-token' });
  expect(fetch).not.toHaveBeenCalled();
});
