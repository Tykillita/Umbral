import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
const resolveApi = vi.hoisted(() => vi.fn());
vi.mock('../lib/api', () => ({ resolveApi }));
vi.mock('../lib/auth', () => ({ initAuth: vi.fn().mockResolvedValue({ mode: 'public', uid: null, error: null }) }));
afterEach(cleanup);
it('un fallo de arranque permite un reintento real con estado propio', async () => {
  resolveApi.mockRejectedValueOnce(new Error('El servicio está iniciando.'));
  resolveApi.mockImplementation((progress: (value: unknown) => void) => { progress({ attempt: 2, elapsedMs: 3000, message: 'Seguimos intentando la conexión…' }); return new Promise(() => {}); });
  render(<App />);
  expect((await screen.findByRole('alert')).textContent).toContain('El servicio está iniciando.');
  fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
  expect(await screen.findByText('Seguimos intentando la conexión…')).toBeTruthy();
  expect(resolveApi).toHaveBeenCalledTimes(2); expect(screen.queryByTestId('mock-banner')).toBeNull();
});
