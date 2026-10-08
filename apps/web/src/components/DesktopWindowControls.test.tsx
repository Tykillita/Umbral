import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import DesktopWindowControls from './DesktopWindowControls';

afterEach(() => {
  cleanup();
  delete (window as { umbralDesktop?: unknown }).umbralDesktop;
  document.documentElement.classList.remove('desktop-shell');
});

function bridge() {
  let listener: ((s: { maximized: boolean }) => void) | undefined;
  const controls = {
    minimize: vi.fn().mockResolvedValue({ maximized: false }),
    toggleMaximize: vi.fn().mockResolvedValue({ maximized: true }),
    close: vi.fn().mockResolvedValue({ maximized: false }),
    getState: vi.fn().mockResolvedValue({ maximized: false }),
    onStateChange: vi.fn((cb) => { listener = cb; return () => { listener = undefined; }; }),
  };
  (window as { umbralDesktop?: unknown }).umbralDesktop = { windowControls: controls };
  return { controls, emit: (s: { maximized: boolean }) => listener?.(s) };
}

it('en el navegador no pinta nada ni reserva espacio', () => {
  const { container } = render(<DesktopWindowControls />);
  expect(container.firstChild).toBeNull();
  expect(document.documentElement.classList.contains('desktop-shell')).toBe(false);
});

it('en escritorio ofrece minimizar, maximizar/restaurar y cerrar con botones propios', async () => {
  const { controls, emit } = bridge();
  render(<DesktopWindowControls />);
  expect(document.documentElement.classList.contains('desktop-shell')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Minimizar la ventana' }));
  expect(controls.minimize).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Maximizar la ventana' }));
  expect(controls.toggleMaximize).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Restaurar la ventana' })).toBeTruthy());
  emit({ maximized: false });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Maximizar la ventana' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Cerrar Umbral' }));
  expect(controls.close).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[title]')).toBeNull();
});
