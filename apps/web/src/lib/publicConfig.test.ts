import { afterEach, beforeEach, expect, it, vi } from 'vitest';
beforeEach(() => { vi.resetModules(); vi.stubEnv('PUBLIC_API_URL', ''); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
it('public-config.json valida Render HTTPS y localhost sólo durante verificación local', async () => {
  const { validatePublicApiUrl } = await import('./publicConfig');
  expect(validatePublicApiUrl('https://umbral-api.onrender.com', 'site-umbral.web.app')).toBe('https://umbral-api.onrender.com');
  expect(validatePublicApiUrl('http://127.0.0.1:8000', 'localhost')).toBe('http://127.0.0.1:8000');
  for (const value of ['https://user:secret@umbral-api.onrender.com', 'http://umbral-api.onrender.com', 'https://umbral-api.onrender.com/path', 'https://umbral-api.onrender.com?redirect=x', 'https://umbral-api.onrender.com.attacker.invalid']) expect(() => validatePublicApiUrl(value, 'site-umbral.web.app')).toThrow(/requiere HTTPS/);
  expect(() => validatePublicApiUrl('http://127.0.0.1:8000', 'site-umbral.web.app')).toThrow(/requiere HTTPS/);
});
it('lee el perfil publicado sin cookies y acepta missing sólo en localhost', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ schemaVersion: 1, apiUrl: 'https://umbral-api.onrender.com' }), { headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetch); const { resolvePublicApiUrl } = await import('./publicConfig');
  expect(await resolvePublicApiUrl()).toBe('https://umbral-api.onrender.com');
  expect(fetch).toHaveBeenCalledWith('/public-config.json', expect.objectContaining({ credentials: 'omit', cache: 'no-store' }));
  fetch.mockResolvedValue(new Response('', { status: 404 })); expect(await resolvePublicApiUrl()).toBe('');
});
it('PUBLIC_API_URL explícito prevalece y no lee config runtime', async () => {
  vi.stubEnv('PUBLIC_API_URL', 'https://explicit-api.onrender.com');
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); const { resolvePublicApiUrl } = await import('./publicConfig');
  expect(await resolvePublicApiUrl()).toBe('https://explicit-api.onrender.com'); expect(fetch).not.toHaveBeenCalled();
});
it('rechaza configuración HTML y versión desconocida con un error legible', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('<html>Missing</html>', { headers: { 'Content-Type': 'text/html' } }));
  vi.stubGlobal('fetch', fetch); const { resolvePublicApiUrl } = await import('./publicConfig');
  await expect(resolvePublicApiUrl()).rejects.toThrow(/página/);
  fetch.mockResolvedValue(new Response(JSON.stringify({ schemaVersion: 9, apiUrl: 'https://umbral-api.onrender.com' }), { headers: { 'Content-Type': 'application/json' } }));
  await expect(resolvePublicApiUrl()).rejects.toThrow(/schemaVersion=1/);
});
