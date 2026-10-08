import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const sdk = vi.hoisted(() => ({
  initializeApp: vi.fn(() => ({})),
  getAuth: vi.fn(),
  signInAnonymously: vi.fn(),
  connectAuthEmulator: vi.fn(),
}));
vi.mock('firebase/app', () => ({ initializeApp: sdk.initializeApp }));
vi.mock('firebase/auth', () => ({ getAuth: sdk.getAuth, signInAnonymously: sdk.signInAnonymously, connectAuthEmulator: sdk.connectAuthEmulator }));

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  for (const key of ['API_KEY', 'AUTH_DOMAIN', 'PROJECT_ID', 'APP_ID']) {
    vi.stubEnv(`PUBLIC_FIREBASE_${key}`, `test-${key}`);
  }
  vi.stubEnv('PUBLIC_AUTH_MODE', 'firebase');
  vi.stubEnv('PUBLIC_FIREBASE_AUTH_EMULATOR_URL', '');
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe('selección y fallos de autenticación', () => {
  it('conecta el emulador local antes de iniciar la sesión', async () => {
    vi.stubEnv('PUBLIC_FIREBASE_AUTH_EMULATOR_URL', 'http://127.0.0.1:9099');
    const user = { uid: 'emulator-user', getIdToken: vi.fn().mockResolvedValue('emulator-token') };
    sdk.getAuth.mockReturnValue({ currentUser: null });
    sdk.signInAnonymously.mockResolvedValue({ user });
    const auth = await import('./auth');
    expect(await auth.initAuth()).toMatchObject({ mode: 'firebase-anonymous', uid: user.uid, error: null });
    expect(sdk.connectAuthEmulator).toHaveBeenCalledWith(expect.anything(), 'http://127.0.0.1:9099', { disableWarnings: true });
    expect(sdk.connectAuthEmulator.mock.invocationCallOrder[0]).toBeLessThan(sdk.signInAnonymously.mock.invocationCallOrder[0] ?? 0);
  });

  it('rechaza emuladores externos y builds de emulador servidas desde Hosting', async () => {
    const { validateAuthEmulatorUrl } = await import('./auth');
    expect(() => validateAuthEmulatorUrl('http://127.0.0.1:9099', 'site-umbral.web.app')).toThrow(/localhost/);
    expect(() => validateAuthEmulatorUrl('http://localhost.attacker.invalid:9099', 'localhost')).toThrow(/localhost/);
    expect(() => validateAuthEmulatorUrl('http://user:password@localhost:9099', 'localhost')).toThrow(/localhost/);
    expect(() => validateAuthEmulatorUrl('http://localhost:9099/redirect', 'localhost')).toThrow(/localhost/);
  });

  it('local no inicializa Firebase aunque estén los cuatro campos configurados', async () => {
    vi.stubEnv('PUBLIC_AUTH_MODE', 'local');
    const auth = await import('./auth');
    expect(await auth.initAuth()).toEqual({ mode: 'local', uid: null, error: null });
    expect(await auth.getAuthToken()).toBeNull();
    expect(sdk.initializeApp).not.toHaveBeenCalled();
    expect(sdk.signInAnonymously).not.toHaveBeenCalled();
  });

  it('firebase exige configuración completa sin pasar a usuario local', async () => {
    vi.stubEnv('PUBLIC_FIREBASE_APP_ID', '');
    const auth = await import('./auth');
    expect(await auth.initAuth()).toMatchObject({ mode: 'firebase-anonymous', uid: null });
    await expect(auth.getAuthToken()).rejects.toThrow(/cuatro variables/);
    expect(sdk.initializeApp).not.toHaveBeenCalled();
  });

  it('auto rechaza una configuración Firebase parcial en vez de usar local', async () => {
    vi.stubEnv('PUBLIC_AUTH_MODE', 'auto');
    vi.stubEnv('PUBLIC_FIREBASE_APP_ID', '');
    const auth = await import('./auth');
    await expect(auth.getAuthToken()).rejects.toThrow(/cuatro variables/);
  });

  it('el error de login queda visible y no permite solicitudes sin Bearer', async () => {
    sdk.getAuth.mockReturnValue({ currentUser: null });
    sdk.signInAnonymously.mockRejectedValue(new Error('auth/network-request-failed'));
    const auth = await import('./auth');
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const { HttpApi } = await import('./api/client');
    await expect(new HttpApi('', auth.getAuthToken).topics({})).rejects.toThrow(/auth\/network-request-failed/);
    expect(auth.authState().mode).toBe('firebase-anonymous');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renueva el token de la sesión y rechaza una sesión terminada', async () => {
    const user = { uid: 'anonymous-test', getIdToken: vi.fn().mockResolvedValue('test-token') };
    const session = { currentUser: user as typeof user | null };
    sdk.getAuth.mockReturnValue(session);
    const auth = await import('./auth');
    expect(await auth.getAuthToken()).toBe('test-token');
    expect(sdk.signInAnonymously).not.toHaveBeenCalled();
    session.currentUser = null;
    await expect(auth.getAuthToken()).rejects.toThrow(/sesión de Firebase terminó/);
  });

  it('auto de API no presenta datos mock cuando falla autenticación Firebase', async () => {
    vi.stubEnv('PUBLIC_API_MODE', 'auto');
    vi.stubEnv('PUBLIC_FIREBASE_APP_ID', '');
    const { resolveApi } = await import('./api');
    await expect(resolveApi()).rejects.toThrow(/cuatro variables/);
  });
});

it('public entra sin Firebase ni token aunque existan variables Firebase', async () => {
  vi.stubEnv('PUBLIC_AUTH_MODE', 'public');
  const auth = await import('./auth');
  expect(await auth.initAuth()).toEqual({ mode: 'public', uid: null, error: null });
  expect(await auth.getAuthToken()).toBeNull();
  expect(sdk.initializeApp).not.toHaveBeenCalled();
  expect(sdk.signInAnonymously).not.toHaveBeenCalled();
});