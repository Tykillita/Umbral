import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UmbralApi } from '../lib/api/client';
import type { Route } from '../lib/router';
import { AppContext } from './context';
import { ExportToast } from './App';
import { SettingsPanel } from './SettingsPanel';
import { getThemePreference, THEME_PREFERENCE_STORAGE_KEY } from '../lib/themePreference';

beforeEach(() => {
  localStorage.removeItem(THEME_PREFERENCE_STORAGE_KEY);
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  cleanup();
  localStorage.removeItem(THEME_PREFERENCE_STORAGE_KEY);
  document.documentElement.removeAttribute('data-theme');
});

function mountSettings() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const showToast = vi.fn();
  const value = {
    api: { kind: 'mock' } as unknown as UmbralApi,
    mockReason: null,
    route: { view: 'agenda' } as Route,
    go: vi.fn(),
    toast: null,
    showToast,
    dismissToast: vi.fn(),
    reviewer: '',
    setReviewer: vi.fn(),
    openAssistant: vi.fn(),
    authMode: 'public' as const,
  };
  const view = render(
    <QueryClientProvider client={queryClient}>
      <AppContext.Provider value={value}><SettingsPanel /></AppContext.Provider>
    </QueryClientProvider>,
  );
  return { ...view, showToast };
}

describe('panel flotante de configuración', () => {
  it('abre desde la tuerca, muestra movimiento y devuelve el foco al cerrar con Escape', async () => {
    mountSettings();
    const trigger = screen.getByTestId('settings-toggle');
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Configuración' });
    expect(trigger.getAttribute('aria-controls')).toBe('settings-dialog');
    expect(dialog.id).toBe('settings-dialog');
    expect(screen.getByRole('radiogroup', { name: 'Movimiento reducido' })).toBeTruthy();
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('cierra al pulsar fuera del panel y conserva el foco de retorno', async () => {
    mountSettings();
    const trigger = screen.getByTestId('settings-toggle');
    fireEvent.click(trigger);
    const layer = screen.getByTestId('settings-dialog-layer');
    fireEvent.mouseDown(layer);
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('integra Preferencias y Conexiones en el encabezado y conserva los saltos', () => {
    mountSettings();
    fireEvent.click(screen.getByTestId('settings-toggle'));
    const dialog = screen.getByRole('dialog', { name: 'Configuración' });
    const header = dialog.querySelector('header');
    const nav = header?.querySelector('nav[aria-label="Secciones de configuración"]');
    expect(nav).toBeTruthy();

    const preferences = document.getElementById('settings-preferences')!;
    const connections = document.getElementById('settings-connections')!;
    const preferencesScroll = vi.fn();
    const connectionsScroll = vi.fn();
    preferences.scrollIntoView = preferencesScroll;
    connections.scrollIntoView = connectionsScroll;

    fireEvent.click(screen.getByRole('button', { name: 'Preferencias' }));
    fireEvent.click(screen.getByRole('button', { name: 'Conexiones' }));
    expect(preferencesScroll).toHaveBeenCalledWith({ block: 'start' });
    expect(connectionsScroll).toHaveBeenCalledWith({ block: 'start' });
  });

  it('aplica el tema TVN al elegirlo, lo persiste y permite volver al original', () => {
    mountSettings();
    fireEvent.click(screen.getByTestId('settings-toggle'));

    const theme = screen.getByRole('combobox', { name: 'Tema' });
    expect(theme.getAttribute('data-value')).toBe('original');
    fireEvent.click(theme);
    fireEvent.click(screen.getByRole('option', { name: /TVN Noticias/ }));

    expect(document.documentElement.dataset.theme).toBe('tvn');
    expect(localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY)).toBe('tvn');
    expect(theme.getAttribute('data-value')).toBe('tvn');

    fireEvent.click(theme);
    fireEvent.click(screen.getByRole('option', { name: /Original/ }));
    expect(document.documentElement.dataset.theme).toBe('original');
    expect(localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY)).toBe('original');
  });

  it('restaura el tema guardado y trata valores inválidos como Original', () => {
    localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, 'tvn');
    expect(getThemePreference()).toBe('tvn');

    localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, 'invalido');
    document.documentElement.dataset.theme = 'tvn';
    expect(getThemePreference()).toBe('original');
  });
});

describe('aviso compacto', () => {
  it('conserva título, descripción y enlace completos para tecnologías de asistencia', () => {
    const title = 'Notion aún no está conectado';
    const description = 'Configura la integración y comparte la página completa de destino para poder exportar la ficha vigente.';
    const onDismiss = vi.fn();
    render(<ExportToast anchor="toggle" onDismiss={onDismiss} toast={{ id: 1, tone: 'info', title, description, durationMs: 60_000, actionLabel: 'Abrir configuración', actionHref: 'https://umbral.example/configuracion' }} />);
    const toast = screen.getByRole('status');
    expect(toast.textContent).toContain(title);
    expect(toast.textContent).toContain(description);
    expect(screen.getByRole('link', { name: /Abrir configuración/ }).getAttribute('href')).toBe('https://umbral.example/configuracion');
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar aviso' }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('se descarta automáticamente cuando vence su duración temporal', () => {
    vi.useFakeTimers();
    try {
      const onDismiss = vi.fn();
      render(<ExportToast anchor="toggle" onDismiss={onDismiss} toast={{ id: 2, tone: 'info', title: 'ChatGPT no está listo' }} />);
      expect(onDismiss).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(6_499); });
      expect(onDismiss).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(1); });
      expect(onDismiss).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});
