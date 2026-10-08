import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';

const resolveApi = vi.hoisted(() => vi.fn());
vi.mock('../lib/api', () => ({ resolveApi }));
vi.mock('../lib/auth', () => ({
  initAuth: vi.fn().mockResolvedValue({ mode: 'firebase-anonymous', uid: null, error: 'Firebase requiere las cuatro variables PUBLIC_FIREBASE_*.' }),
}));
afterEach(cleanup);

it('el arranque muestra el fallo Firebase sin abrir agenda ni usar una API local/mock', async () => {
  render(<App />);
  expect((await screen.findByRole('alert')).textContent).toMatch(/cuatro variables/);
  expect(screen.getByTestId('app-boot-error')).toBeTruthy();
  expect(screen.queryByTestId('agenda-view')).toBeNull();
  expect(resolveApi).not.toHaveBeenCalled();
});
