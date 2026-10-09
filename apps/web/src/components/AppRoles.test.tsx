import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import { MockApi } from '../lib/mock/mockApi';
import { chooseRole, type DemoRole } from '../lib/session';

vi.mock('../lib/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/auth')>()),
  initAuth: vi.fn().mockResolvedValue({ mode: 'public', uid: null, error: null }),
  authState: () => ({ mode: 'public', uid: null, error: null }),
}));
vi.mock('../lib/api', () => ({
  resolveApi: vi.fn(async () => ({ api: new MockApi(), reason: 'fixture explícito' })),
}));
beforeAll(() => {
  Object.defineProperty(window, 'scrollTo', { value: vi.fn(), configurable: true });
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true });
  Object.defineProperty(window, 'matchMedia', {
    value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    configurable: true,
  });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
});
beforeEach(() => {
  localStorage.clear();
  window.location.hash = '';
});
afterEach(cleanup);
it('elige un rol sin contraseña y cambiar conserva el trabajo', async () => {
  localStorage.setItem('draft-previous', 'conservar');
  render(<App />);
  fireEvent.click(await screen.findByTestId('role-juror'));
  await screen.findByTestId('nav-mesa');
  expect(screen.getByTestId('active-role').textContent).toBe('Jurado');
  fireEvent.click(screen.getByTestId('role-change'));
  fireEvent.click(screen.getByTestId('role-producer'));
  await screen.findByTestId('nav-borradores');
  expect(screen.queryByTestId('nav-agenda')).toBeNull();
  expect(screen.queryByTestId('nav-mesa')).toBeNull();
  expect(localStorage.getItem('draft-previous')).toBe('conservar');
});
it.each(['editor', 'producer', 'reviewer', 'juror'] as DemoRole[])(
  'protege rutas directas para %s y mantiene las vistas comunes',
  async (role) => {
    chooseRole(role, null);
    window.location.hash = role === 'editor' ? '#/borradores' : '#/agenda';
    render(<App />);
    await screen.findByTestId('nav-etiquetar');
    expect(screen.getByTestId('nav-fuentes')).toBeTruthy();
    if (role === 'editor') {
      expect(screen.queryByTestId('draft-view')).toBeNull();
      await waitFor(() => expect(window.location.hash).toBe('#/agenda'));
    }
    if (role === 'producer' || role === 'reviewer') {
      expect(screen.queryByTestId('agenda-view')).toBeNull();
      await waitFor(() => expect(window.location.hash).toBe('#/ficha'));
    }
    if (role === 'juror') {
      expect(
        screen.getAllByRole('link').filter((link) => link.getAttribute('data-testid')?.startsWith('nav-')),
      ).toHaveLength(6);
    }
  },
);
