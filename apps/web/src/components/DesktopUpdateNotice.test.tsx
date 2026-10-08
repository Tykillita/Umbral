import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DesktopUpdateNotice from './DesktopUpdateNotice';
import type { DesktopUpdateState } from '../lib/desktop';

afterEach(() => { cleanup(); delete window.umbralDesktop; });

function setup(state: DesktopUpdateState) {
  let listener: ((next: DesktopUpdateState) => void) | undefined;
  const bridge = {
    getUpdateState: vi.fn(async () => state),
    checkForUpdates: vi.fn(async () => undefined),
    installUpdate: vi.fn(async () => true),
    onUpdateState: vi.fn((callback: (next: DesktopUpdateState) => void) => {
      listener = callback;
      return () => { listener = undefined; };
    }),
  };
  window.umbralDesktop = bridge as unknown as typeof window.umbralDesktop;
  return { bridge, emit: (next: DesktopUpdateState) => listener?.(next) };
}

describe('aviso de actualizaciones del escritorio', () => {
  it('no aparece para una app al día y muestra el progreso al detectar una release', async () => {
    const { emit } = setup({ status: 'idle' });
    render(<DesktopUpdateNotice />);
    await waitFor(() => expect(window.umbralDesktop?.getUpdateState).toHaveBeenCalled());
    expect(screen.queryByTestId('desktop-update-notice')).toBeNull();
    act(() => emit({ status: 'downloading', version: '0.2.0', percent: 42 }));
    expect(screen.getByText(/Descargando una actualización/)).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: 'Descarga de actualización' }).getAttribute('aria-valuenow')).toBe('42');
  });

  it('solo ofrece reiniciar cuando la descarga terminó', async () => {
    const { bridge, emit } = setup({ status: 'idle' });
    render(<DesktopUpdateNotice />);
    act(() => emit({ status: 'downloaded', version: '0.2.0' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reiniciar e instalar' }));
    await waitFor(() => expect(bridge.installUpdate).toHaveBeenCalledOnce());
  });

  it('permite cerrar el aviso durante la descarga sin reabrirlo por cada avance', () => {
    const { emit } = setup({ status: 'idle' });
    render(<DesktopUpdateNotice />);
    act(() => emit({ status: 'downloading', version: '0.2.0', percent: 10 }));
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar aviso de actualización' }));
    act(() => emit({ status: 'downloading', version: '0.2.0', percent: 20 }));
    expect(screen.queryByTestId('desktop-update-notice')).toBeNull();
  });

  it('ofrece reintentar ante un error de red y permite cerrar el aviso', async () => {
    const { bridge, emit } = setup({ status: 'idle' });
    render(<DesktopUpdateNotice />);
    act(() => emit({ status: 'error' }));
    fireEvent.click(screen.getByRole('button', { name: 'Volver a comprobar' }));
    expect(bridge.checkForUpdates).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar aviso de actualización' }));
    expect(screen.queryByTestId('desktop-update-notice')).toBeNull();
  });
});
