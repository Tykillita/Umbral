import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DesktopUpdateSettings } from './DesktopUpdateSettings';
import type { DesktopUpdateState } from '../lib/desktop';

afterEach(() => { cleanup(); delete window.umbralDesktop; });

function setup(state: DesktopUpdateState) {
  let listener: ((next: DesktopUpdateState) => void) | undefined;
  const bridge = {
    autoUpdateEnabled: true,
    getUpdateState: vi.fn(async () => state),
    checkForUpdates: vi.fn(async () => undefined),
    installUpdate: vi.fn(async () => true),
    updateNow: vi.fn(async () => true),
    setAutoUpdateEnabled: vi.fn(async (enabled: boolean) => enabled),
    onUpdateState: vi.fn((callback: (next: DesktopUpdateState) => void) => {
      listener = callback;
      return () => { listener = undefined; };
    }),
  };
  window.umbralDesktop = bridge as unknown as typeof window.umbralDesktop;
  return { bridge, emit: (next: DesktopUpdateState) => listener?.(next) };
}

describe('preferencias de actualización del escritorio', () => {
  it('muestra el interruptor, guarda el cambio y permite buscar', async () => {
    const { bridge } = setup({ status: 'idle', autoUpdateEnabled: true });
    render(<DesktopUpdateSettings />);
    const toggle = screen.getByRole('checkbox', { name: /Buscar e instalar actualizaciones/ });
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(toggle);
    await waitFor(() => expect(bridge.setAutoUpdateEnabled).toHaveBeenCalledWith(false));
    expect(screen.getByTestId('desktop-update-status').textContent).toContain('No hay actualizaciones pendientes');
    fireEvent.click(screen.getByTestId('desktop-check-updates'));
    await waitFor(() => expect(bridge.checkForUpdates).toHaveBeenCalledOnce());
  });

  it('habilita «Actualizar ahora» solo cuando hay una versión disponible y la lanza', async () => {
    const { bridge, emit } = setup({ status: 'idle' });
    render(<DesktopUpdateSettings />);
    const updateNow = screen.getByTestId('desktop-update-now') as HTMLButtonElement;
    expect(updateNow.disabled).toBe(true);
    act(() => emit({ status: 'available', version: '0.3.0', autoUpdateEnabled: false }));
    expect(screen.getByTestId('desktop-update-status').textContent).toContain('0.3.0 está disponible');
    expect(updateNow.disabled).toBe(false);
    fireEvent.click(updateNow);
    await waitFor(() => expect(bridge.updateNow).toHaveBeenCalledOnce());
  });

  it('no aparece fuera de la aplicación de escritorio', () => {
    const { unmount } = render(<DesktopUpdateSettings />);
    expect(screen.queryByTestId('desktop-update-settings')).toBeNull();
    unmount();
  });
});
