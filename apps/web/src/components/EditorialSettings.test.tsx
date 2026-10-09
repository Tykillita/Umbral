// Pruebas de interacción con transportes controlados; no representan sesiones OAuth reales.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, HttpApi } from '../lib/api/client';
import { MockApi } from '../lib/mock/mockApi';
import { MOCK_HEALTH, MOCK_RULES } from '../lib/mock/data';
import { AppContext } from './context';
import { ConnectionsCard, RulesEditor } from './EditorialSettings';
import { Modal } from './ui/controls';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(ui: React.ReactNode, api: MockApi) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AppContext.Provider value={{ api, route: { view: 'fuentes' }, go: vi.fn(), toast: null, showToast: vi.fn(), dismissToast: vi.fn(), reviewer: 'Revisor de prueba', setReviewer: vi.fn(), mockReason: null, openAssistant: vi.fn(), authMode: 'local' }}>{ui}</AppContext.Provider></QueryClientProvider>);
}
function controlledLive() { const api = new MockApi(); Object.defineProperty(api, 'kind', { value: 'live' }); return api; }

describe('política editorial y conexiones personales', () => {
  it('valida suma100, envía responsable/motivo/versión y refresca la política', async () => {
    const api = controlledLive();
    vi.spyOn(api, 'rules').mockResolvedValue(MOCK_RULES);
    const updated = { ...MOCK_RULES, version: 1, rulesVersion: 'scoring-v2', weights: { R: 40, I: 15, U: 20, N: 15, E: 10 }, history: [{ version: 1, rulesVersion: 'scoring-v2', weights: { R: 40, I: 15, U: 20, N: 15, E: 10 }, author: 'Revisor de prueba', reason: 'Dar mayor peso a Panamá', at: '2026-10-07T15:00:00Z' }] };
    const update = vi.spyOn(api, 'updateRules').mockResolvedValue(updated);
    mount(<RulesEditor />, api);
    await screen.findByTestId('rules-weight-R');
    fireEvent.change(screen.getByTestId('rules-reason'), { target: { value: 'Dar mayor peso a Panamá' } });
    fireEvent.change(screen.getByTestId('rules-weight-R'), { target: { value: '40' } });
    expect((screen.getByTestId('rules-save') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId('rules-weight-I'), { target: { value: '15' } });
    fireEvent.click(screen.getByTestId('rules-save'));
    expect((await screen.findByTestId('rules-saved')).textContent).toContain('scoring-v2');
    expect(update).toHaveBeenCalledWith({ expectedVersion: 0, weights: updated.weights, author: 'Revisor de prueba', reason: 'Dar mayor peso a Panamá' });
    expect(screen.getByTestId('rules-history').textContent).toContain('Dar mayor peso a Panamá');
  });
  it('conserva el formulario tras409 y exige recargar explícitamente', async () => {
    const api = controlledLive();
    vi.spyOn(api, 'rules').mockResolvedValue(MOCK_RULES);
    vi.spyOn(api, 'updateRules').mockRejectedValue(new ApiError(409, { code: 'conflicto_de_version', message: 'Versión antigua', details: { currentVersion: 2 } }));
    mount(<RulesEditor />, api); await screen.findByTestId('rules-weight-R');
    fireEvent.change(screen.getByTestId('rules-reason'), { target: { value: 'Comentario que debe conservarse' } });
    fireEvent.click(screen.getByTestId('rules-save'));
    await screen.findByText('La política cambió mientras editabas');
    expect((screen.getByTestId('rules-reason') as HTMLInputElement).value).toBe('Comentario que debe conservarse');
    expect(screen.queryByTestId('rules-saved')).toBeNull();
  });
  it('no consulta conexiones personales desde web o demostración', async () => {
    const api = new MockApi(); const connections = vi.spyOn(api, 'connections');
    mount(<ConnectionsCard />, api);
    await screen.findAllByText('Disponible en la aplicación local');
    expect(connections).not.toHaveBeenCalled();
  });
  it('en offline muestra perfiles sin iniciar OAuth ni consultar catálogo', async () => {
    const api = controlledLive();
    vi.spyOn(api, 'health').mockResolvedValue({ ...MOCK_HEALTH, localMode: true, authMode: 'local', offline: true });
    vi.spyOn(api, 'connections').mockResolvedValue({ available: false, reason: 'Offline', activeProfileId: 'one', profiles: [{ profileId: 'one', label: 'Perfil de prueba', email: null, connected: true, active: true, planUsageEnabled: true, model: 'modelo-de-prueba' }] });
    const start = vi.spyOn(api, 'startConnection'); const models = vi.spyOn(api, 'connectionModels');
    mount(<ConnectionsCard />, api); await screen.findByText('Perfil de prueba');
    expect((screen.getByRole('button', { name: 'Iniciar sesión con ChatGPT' }) as HTMLButtonElement).disabled).toBe(true);
    expect(start).not.toHaveBeenCalled(); expect(models).not.toHaveBeenCalled();
  });
  it('detecta la cuenta cuando el callback OAuth vuelve desde el navegador', async () => {
    const api = controlledLive();
    vi.spyOn(api, 'health').mockResolvedValue({ ...MOCK_HEALTH, localMode: true, authMode: 'local', offline: false });
    const disconnected = { available: true, reason: null, activeProfileId: null, profiles: [] };
    const connected = { available: true, reason: null, activeProfileId: 'profile-1', profiles: [{
      profileId: 'profile-1', label: 'Cuenta ChatGPT', email: null, connected: true, active: true,
      planUsageEnabled: true, model: null,
    }] };
    let statusCalls = 0;
    vi.spyOn(api, 'connections').mockImplementation(async () => ++statusCalls === 1 ? disconnected : connected);
    vi.spyOn(api, 'startConnection').mockResolvedValue({
      authorizationUrl: 'https://auth.openai.com/oauth/authorize?state=fixture', expiresIn: 600,
    });
    vi.spyOn(api, 'connectionModels').mockResolvedValue({ profileId: 'profile-1', models: [], selectedModel: null });
    const onConnected = vi.fn();

    mount(<ConnectionsCard onConnected={onConnected} />, api);
    fireEvent.click(await screen.findByRole('button', { name: 'Iniciar sesión con ChatGPT' }));
    await screen.findByTestId('chatgpt-login-link');

    await waitFor(() => expect(onConnected).toHaveBeenCalledWith('chatgpt'), { timeout: 5000 });
    expect(await screen.findByText('Sesión de ChatGPT reconocida en este equipo.')).toBeTruthy();
  });
  it('permite elegir y guardar un modelo desde el modal de cuentas', async () => {
    const api = controlledLive();
    vi.spyOn(api, 'health').mockResolvedValue({ ...MOCK_HEALTH, localMode: true, authMode: 'local', offline: false });
    vi.spyOn(api, 'connections').mockResolvedValue({ available: true, reason: null, activeProfileId: 'profile-1', profiles: [{
      profileId: 'profile-1', label: 'Cuenta ChatGPT', email: null, connected: true, active: true,
      planUsageEnabled: true, model: null,
    }] });
    const catalog = [{ slug: 'gpt-test', displayName: 'GPT de prueba' }];
    let selectedModel: string | null = null;
    vi.spyOn(api, 'connectionModels').mockImplementation(async () => ({ profileId: 'profile-1', models: catalog, selectedModel }));
    const selectModel = vi.spyOn(api, 'selectConnectionModel').mockImplementation(async (model) => {
      selectedModel = model;
      return { profileId: 'profile-1', models: catalog, selectedModel };
    });

    mount(<Modal open title="Cuentas y modelos" onClose={vi.fn()}><ConnectionsCard /></Modal>, api);
    const trigger = await screen.findByRole('combobox', { name: 'Modelo de la cuenta activa' });
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole('option', { name: 'GPT de prueba' }));

    await waitFor(() => expect(selectModel).toHaveBeenCalledWith('gpt-test'));
    await waitFor(() => expect(trigger.textContent).toContain('GPT de prueba'));
    expect(screen.queryByTestId('chatgpt-model-required')).toBeNull();
  });
  it('cliente HTTP envía alcance y bearer; guarda pesos con el contrato', async () => {
    const transport = vi.fn().mockImplementation(async () => new Response(JSON.stringify(MOCK_RULES), { status: 200, headers: { 'Content-Type': 'application/json' } })); vi.stubGlobal('fetch', transport);
    const api = new HttpApi('http://127.0.0.1:8000', async () => 'token-controlado');
    await api.topics({ scope: 'all', limit: 5 });
    expect(transport.mock.calls[0]?.[0]).toContain('scope=all');
    expect(transport.mock.calls[0]?.[1].headers.Authorization).toBe('Bearer token-controlado');
    const body = { expectedVersion: 0, weights: MOCK_RULES.weights, author: 'Prueba', reason: 'Prueba del transporte' };
    await api.updateRules(body);
    await waitFor(() => expect(transport.mock.calls[1]?.[1].body).toBe(JSON.stringify(body)));
  });
});
