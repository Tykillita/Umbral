import { afterEach, beforeEach, expect, it, vi } from 'vitest';

type Listener = () => void;
class FakeWorker {
  state = 'installing';
  private listeners: Listener[] = [];
  addEventListener(_: string, listener: Listener) { this.listeners.push(listener); }
  set(state: string) { this.state = state; this.listeners.forEach((listener) => listener()); }
}

async function setup(controller: boolean) {
  vi.resetModules();
  const worker = new FakeWorker();
  let updateFound: Listener = () => {};
  const registration = {
    installing: worker, waiting: null,
    addEventListener: (_: string, listener: Listener) => { updateFound = listener; },
    update: vi.fn().mockResolvedValue(undefined),
  };
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { controller: controller ? {} : null, addEventListener: vi.fn(), register: vi.fn().mockResolvedValue(registration) },
  });
  vi.stubGlobal('isSecureContext', true);
  vi.stubEnv('PROD', true);
  const pwa = await import('./pwa');
  const seen: boolean[] = [];
  pwa.subscribeUpdateAvailable((value) => seen.push(value));
  pwa.registerServiceWorker();
  await vi.waitFor(() => expect(navigator.serviceWorker.register).toHaveBeenCalled());
  await Promise.resolve();
  return { worker, seen, updateFound: () => updateFound() };
}

beforeEach(() => { vi.stubEnv('PROD', true); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it('avisa cuando una versión nueva queda instalada y esperando', async () => {
  const { worker, seen } = await setup(true);
  worker.set('installed');
  expect(seen.at(-1)).toBe(true);
});

it('quita el aviso cuando el worker que esperaba se activa o queda obsoleto', async () => {
  const { worker, seen } = await setup(true);
  worker.set('installed');
  expect(seen.at(-1)).toBe(true);
  worker.set('activated');
  expect(seen.at(-1)).toBe(false);
});

it('en la primera instalación (sin controlador) no hay aviso', async () => {
  const { worker, seen } = await setup(false);
  worker.set('installed');
  expect(seen.at(-1)).toBe(false);
});
