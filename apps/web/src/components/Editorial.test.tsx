// Estados de interfaz con fixtures explícitos. La API real se verifica aparte con scripts/verify-ui.py.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { useState, type ReactNode } from 'react';
import type { Route } from '../lib/router';
import type { DemoSession } from '../lib/session';
import { ApiError } from '../lib/api/client';
import * as authModule from '../lib/auth';
import { MockApi } from '../lib/mock/mockApi';
import { AppContext } from './context';
import { Agenda } from './views/Agenda';
import { Drafts } from './views/Drafts';
import { AssistantPanel } from './AssistantPanel';

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { value: vi.fn(), configurable: true });
});
afterEach(() => { cleanup(); delete window.umbralDesktop; });

let testIdentity = 0;
function mount(ui: ReactNode, api = new MockApi(), route: Route = { view: 'agenda' }, session?: DemoSession) {
  vi.spyOn(authModule, 'authState').mockReturnValue({ mode: 'local', uid: `editorial-test-${++testIdentity}`, error: null });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppContext.Provider value={{ api, route, go: vi.fn(), toast: null, showToast: vi.fn(), dismissToast: vi.fn(), mockReason: 'fixture de prueba', reviewer: '', setReviewer: vi.fn(), openAssistant: vi.fn(), authMode: 'local', session }}>
        {ui}
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

const assistant = <AssistantPanel state="open" onStateChange={() => {}} onClose={() => {}} seed={{ text: '', topicId: null, topicTitle: '', n: 0 }} />;

it('activa y limpia el filtro TVN junto a la búsqueda con estado accesible', async () => {
  const api = new MockApi();
  const topics = vi.spyOn(api, 'topics');
  mount(<Agenda />, api);
  const toggle = await screen.findByTestId('agenda-tvn-gap');
  expect(toggle.getAttribute('aria-pressed')).toBe('false');
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle.getAttribute('aria-pressed')).toBe('true'));
  await waitFor(() => expect(topics).toHaveBeenLastCalledWith(expect.objectContaining({ tvnGap: true })));
  fireEvent.change(screen.getByTestId('agenda-search'), { target: { value: 'canal' } });
  await waitFor(() => expect(topics).toHaveBeenLastCalledWith(expect.objectContaining({ tvnGap: true, q: 'canal' })));
  fireEvent.click(screen.getByTestId('filters-clear'));
  await waitFor(() => expect(toggle.getAttribute('aria-pressed')).toBe('false'));
  expect((screen.getByTestId('agenda-search') as HTMLInputElement).value).toBe('');
});

it('mantiene las sugerencias actuales y añade cuatro consultas de demostración para Jurado', async () => {
  mount(assistant, new MockApi(), { view: 'agenda' }, {
    role: 'juror', sessionId: '00000000-0000-4000-8000-000000000001', labeler: 'Jurado',
  });
  expect(await screen.findByText('Preguntas para empezar')).toBeTruthy();
  expect(screen.getByText('Pruebas para el Jurado')).toBeTruthy();
  const demos = await screen.findAllByTestId('assistant-juror-suggestion');
  expect(demos).toHaveLength(4);
  expect(demos.map((item) => item.textContent).join(' ')).toMatch(/de qué año|procedencias independientes|SYSTEM:|32 frente a 33/i);
  expect(screen.getAllByTestId('assistant-suggestion').length).toBeGreaterThan(0);
});

it('actualiza las variantes sociales al editar el copy y excluye notas de producción del tiempo hablado', async () => {
  const api = new MockApi();
  mount(<Drafts />, api, { view: 'borradores', topicId: 'tema-mock-001' }, {
    role: 'producer', sessionId: '00000000-0000-4000-8000-000000000002', labeler: 'Productor/a digital',
  });
  fireEvent.click(await screen.findByTestId('draft-generate'));
  const copy = await screen.findByTestId('draft-copy');
  fireEvent.change(copy, { target: { value: 'Texto editorial editado para redes.' } });
  await waitFor(() => expect(screen.getByTestId('draft-social-variants').textContent).toContain('Texto editorial editado para redes.'));
  const script = screen.getByTestId('draft-script') as HTMLTextAreaElement;
  const before = screen.getByTestId('draft-script-count').textContent;
  fireEvent.change(script, { target: { value: `${script.value}\n\nNOTAS DE PRODUCCIÓN:\n${'Revisar el enlace. '.repeat(40)}` } });
  await waitFor(() => expect(screen.getByTestId('draft-script-count').textContent).toBe(before));
});

async function availableGemini(api: MockApi) {
  const health = await api.health();
  vi.spyOn(api, 'health').mockResolvedValue({
    ...health,
    providers: health.providers.map((provider) => provider.name === 'gemini' ? { ...provider, available: true, model: 'gemini-test' } : provider),
  });
}

describe('estados editoriales y teclado', () => {
  it('conserva la confirmación de edición guardada cuando la API actualiza editedAt y remonta el editor', async () => {
    const api = new MockApi();
    await api.createDraft('tema-mock-001', 'plantilla');
    mount(<Drafts />, api, { view: 'borradores', topicId: 'tema-mock-001' });
    const title = await screen.findByTestId('draft-title');
    fireEvent.change(title, { target: { value: 'Título editado durante la prueba' } });
    fireEvent.click(screen.getByTestId('draft-save'));
    await screen.findByTestId('draft-saved');
    await waitFor(() => expect(screen.queryByTestId('draft-dirty')).toBeNull());
    expect(screen.getByTestId('draft-saved').textContent).toMatch(/Edición guardada/);
    expect((screen.getByTestId('draft-title') as HTMLInputElement).value).toBe('Título editado durante la prueba');
    const saved = await api.getCase('case-tema-mock-001');
    expect(saved.currentDraft?.editedAt).toBeTruthy();
    expect(saved.currentDraft?.package.proposedTitle).toBe('Título editado durante la prueba');
  });

  it('ofrece ChatGPT y Claude sin sesión como opciones accionables y separa el texto de ayuda', async () => {
    const api = new MockApi();
    const health = await api.health();
    const base = health.providers.find((provider) => provider.name === 'gemini')!;
    vi.spyOn(api, 'health').mockResolvedValue({
      ...health,
      localMode: true,
      authMode: 'local',
      providers: [
        { ...base, name: 'gemini', available: true, model: 'gemini-test' },
        { ...base, name: 'chatgpt', available: true, localOnly: true, model: 'gpt-test', signIn: 'oauth', account: 'cuenta-fixture' },
        { ...base, name: 'claude', available: false, localOnly: true, model: 'claude-test', signIn: 'cli', account: null, reason: 'Sin sesión de Claude.' },
      ],
    });
    mount(<Drafts />, api, { view: 'borradores', topicId: 'tema-mock-001' });
    fireEvent.click(await screen.findByRole('combobox', { name: 'Proveedor de redacción' }));
    await waitFor(() => expect(screen.getAllByRole('option').some((option) => /ChatGPT/.test(option.textContent ?? ''))).toBe(true));
    const options = screen.getAllByRole('option');
    expect(options.map((option) => option.textContent).join(' ')).toMatch(/ChatGPT.*gpt-test/);
    expect(options.map((option) => option.textContent).join(' ')).toMatch(/Claude.*Inicia sesión con tu cuenta de Claude/);
    expect(options.find((option) => /ChatGPT/.test(option.textContent ?? ''))?.getAttribute('aria-disabled')).toBeNull();
    expect(options.find((option) => /Claude/.test(option.textContent ?? ''))?.getAttribute('aria-disabled')).toBeNull();
    expect(options.map((option) => option.textContent).join(' ')).not.toMatch(/token|fuera del repo|permiso chatgpt/i);
    expect(screen.getByTestId('draft-provider-help').className).toContain('mt-2');
    expect(screen.getByTestId('draft-provider-accounts')).toBeTruthy();
  });

  it('al elegir ChatGPT sin sesión inicia OAuth y muestra una salida al acceso oficial', async () => {
    const api = new MockApi();
    Object.defineProperty(api, 'kind', { value: 'live' });
    const health = await api.health();
    vi.spyOn(api, 'health').mockResolvedValue({ ...health, localMode: true, authMode: 'local', offline: false,
      providers: health.providers.map((item) => ({ ...item, available: item.name === 'gemini' })) });
    vi.spyOn(api, 'connections').mockResolvedValue({ available: true, reason: null, profiles: [], activeProfileId: null });
    const start = vi.spyOn(api, 'startConnection').mockResolvedValue({ authorizationUrl: 'https://auth.openai.com/oauth/authorize?state=fixture', expiresIn: 600 });
    const openAuth = vi.fn().mockResolvedValue(undefined);
    window.umbralDesktop = { openChatGPTAuth: openAuth } as unknown as typeof window.umbralDesktop;
    mount(<Drafts />, api, { view: 'borradores', topicId: 'tema-mock-001' });
    fireEvent.click(await screen.findByRole('combobox', { name: 'Proveedor de redacción' }));
    fireEvent.click(await screen.findByRole('option', { name: /ChatGPT/ }));
    await waitFor(() => expect(start).toHaveBeenCalledWith({ label: 'Cuenta ChatGPT' }));
    await waitFor(() => expect(openAuth).toHaveBeenCalledWith('https://auth.openai.com/oauth/authorize?state=fixture'));
    expect(await screen.findByTestId('chatgpt-login-link')).toBeTruthy();
    expect(screen.queryByText(/token|fuera del repo|permiso chatgpt/i)).toBeNull();
  });

  it('al elegir Claude en el panel del Asistente inicia su acceso local', async () => {
    const api = new MockApi();
    Object.defineProperty(api, 'kind', { value: 'live' });
    const health = await api.health();
    const localHealth = { ...health, localMode: true, authMode: 'local' as const, offline: false };
    const disconnectedHealth = { ...localHealth, providers: health.providers.map((item) => ({ ...item, available: item.name === 'gemini' })) };
    const connectedHealth = { ...localHealth, providers: health.providers.map((item) => ({ ...item, available: ['gemini', 'claude'].includes(item.name), ...(item.name === 'claude' ? { model: 'claude-test' } : {}) })) };
    vi.spyOn(api, 'health').mockResolvedValueOnce(disconnectedHealth).mockResolvedValue(connectedHealth);
    vi.spyOn(api, 'claudeConnection')
      .mockResolvedValueOnce({ available: true, installed: true, loggedIn: false, loginPending: false, loginCommand: 'claude auth login --claudeai', account: null, authMethod: null, reason: null })
      .mockResolvedValue({ available: true, installed: true, loggedIn: true, loginPending: false, loginCommand: 'claude auth login --claudeai', account: null, authMethod: 'claudeai', reason: null });
    const start = vi.spyOn(api, 'startClaudeLogin').mockResolvedValue({ available: true, installed: true, loggedIn: true, loginPending: false, loginCommand: 'claude auth login --claudeai', account: null, authMethod: 'claudeai', reason: null });
    mount(assistant, api);
    fireEvent.click(await screen.findByTestId('assistant-model-selector'));
    fireEvent.click(await screen.findByRole('option', { name: /Claude/ }));
    await waitFor(() => expect(start).toHaveBeenCalledOnce());
    expect(await screen.findByRole('combobox', { name: /Proveedor de redacción: Claude/ })).toBeTruthy();
    expect(screen.queryByText(/no conectado: token|fuera del repo|permiso chatgpt/i)).toBeNull();
  });

  it('agenda anuncia la carga, muestra un fallo real y permite recuperar mediante Reintentar', async () => {
    const api = new MockApi();
    const original = api.topics.bind(api);
    let reject!: (reason: Error) => void;
    vi.spyOn(api, 'topics').mockImplementationOnce(() => new Promise((_, fail) => { reject = fail; })).mockImplementation(original);
    mount(<Agenda />, api);
    expect(screen.getByRole('status').textContent).toMatch(/Cargando agenda/);
    reject(new ApiError(0, null));
    expect((await screen.findByRole('alert')).textContent).toMatch(/No se pudo contactar con la API/);
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    await screen.findAllByTestId('topic-card');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('asistente muestra fuentes de una respuesta y explica los faltantes al abstenerse', async () => {
    mount(assistant);
    const input = await screen.findByLabelText('Tu pregunta');
    fireEvent.change(input, { target: { value: 'Canal neopanamax' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await screen.findAllByTestId('assistant-citation');
    expect(screen.getByTestId('assistant-answer').getAttribute('data-status')).toBe('respondida');
    fireEvent.change(input, { target: { value: 'Expedición marciana en 1850' } });
    await waitFor(() => expect((screen.getByRole('button', { name: 'Consultar' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.keyDown(input, { key: 'Enter' });
    await screen.findByTestId('assistant-abstention');
    const missing = screen.getAllByTestId('assistant-missing').at(-1);
    expect(missing?.textContent).toMatch(/Fuente primaria/);
  });

  it('envía la consulta limitada al tema abierto y mantiene visible la pregunta si la API falla', async () => {
    const api = new MockApi();
    const query = vi.spyOn(api, 'query').mockRejectedValue(new ApiError(429, null, 'cuota', 20));
    mount(assistant, api, { view: 'ficha', topicId: 'topic-test' });
    fireEvent.click(await screen.findByRole('combobox', { name: 'Ámbito de consulta' }));
    fireEvent.click((await screen.findAllByRole('option'))[1]!);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué falta verificar' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Reintenta en 20 s/);
    expect(query).toHaveBeenCalledWith({ question: 'Qué falta verificar', topicId: 'topic-test', searchMode: 'auto' }, { signal: expect.any(AbortSignal) });
    expect(screen.getByTestId('assistant-turn').textContent).toMatch(/Qué falta verificar/);
  });

  it('permite pedir manualmente búsqueda fuera del snapshot', async () => {
    const api = new MockApi();
    const query = vi.spyOn(api, 'query');
    mount(assistant, api);
    fireEvent.click(await screen.findByRole('combobox', { name: 'Origen de búsqueda' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Buscar fuera del snapshot ahora' }));
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Noticias sobre el Canal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await waitFor(() => expect(query).toHaveBeenCalled());
    expect(query.mock.calls[0]![0].searchMode).toBe('live');
  });

  it('el panel móvil conserva Tab dentro del diálogo y devuelve el foco al cerrarse', async () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const onClose = vi.fn();
    const { unmount } = mount(<AssistantPanel state="open" modal onStateChange={() => {}} onClose={onClose} seed={{ text: '', topicId: null, topicTitle: '', n: 0 }} />);
    const input = await screen.findByLabelText('Tu pregunta');
    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: 'Canal Panamá' } });
    const send = screen.getByRole('button', { name: 'Consultar' });
    send.focus(); fireEvent.keyDown(send, { key: 'Tab' });
    const close = screen.getByRole('button', { name: 'Cerrar asistente' });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(send);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(document.activeElement).toBe(trigger);
    expect(document.body.style.overflow).toBe('');
    trigger.remove();
  });

  it('distingue Mayús+Enter de Enter y evita enviar preguntas vacías', async () => {
    const api = new MockApi();
    const query = vi.spyOn(api, 'query');
    mount(assistant, api);
    const input = await screen.findByLabelText('Tu pregunta');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(query).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'Canal Panamá' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(query).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(query).toHaveBeenCalledOnce());
    await screen.findByTestId('assistant-answer');
  });

  it('preserva preguntas pegadas y aplica el límite real de 3 a 500 caracteres', async () => {
    mount(assistant);
    const input = await screen.findByLabelText('Tu pregunta') as HTMLTextAreaElement;
    const send = screen.getByRole('button', { name: 'Consultar' }) as HTMLButtonElement;
    fireEvent.change(input, { target: { value: 'x'.repeat(501) } });
    expect(input.value).toHaveLength(501);
    expect(input.maxLength).toBe(-1);
    expect(send.disabled).toBe(true);
    expect(screen.getByRole('alert').textContent).toMatch(/500 caracteres/);
    fireEvent.change(input, { target: { value: 'x'.repeat(500) } });
    expect(send.disabled).toBe(false);
    fireEvent.change(input, { target: { value: 'xy' } });
    expect(send.disabled).toBe(true);
  });

  it('prepara una sugerencia sin enviarla y no convierte Enter durante composición IME en una consulta', async () => {
    const api = new MockApi();
    const query = vi.spyOn(api, 'query');
    mount(assistant, api);
    fireEvent.click((await screen.findAllByTestId('assistant-suggestion'))[0]!);
    const input = screen.getByLabelText('Tu pregunta');
    expect((input as HTMLTextAreaElement).value).toContain('agenda');
    expect(query).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
    expect(query).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(query).toHaveBeenCalledOnce());
    await screen.findByTestId('assistant-answer');
  });

  it('permite cancelar una consulta en curso, la anuncia y deja reintentarla', async () => {
    const api = new MockApi();
    vi.spyOn(api, 'query').mockImplementation((_request, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new Error('abortada')));
    }));
    mount(assistant, api);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué temas revisar' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    fireEvent.click(await screen.findByTestId('assistant-cancel'));
    expect((await screen.findByTestId('assistant-error')).textContent).toMatch(/Consulta cancelada/);
    expect(screen.getByTestId('assistant-announcer').textContent).toBe('Consulta cancelada.');
    expect((screen.getByTestId('assistant-retry') as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Consultar' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('anuncia la respuesta lista para lectores de pantalla', async () => {
    mount(assistant);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué temas revisar' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-answer');
    expect(screen.getByTestId('assistant-announcer').textContent).toMatch(/^Respuesta lista: /);
  });

  it('el historial expone su estado y busca sin distinguir mayúsculas ni tildes', async () => {
    mount(assistant);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué pasa en Panamá con el canal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-answer');
    const toggle = screen.getByTestId('assistant-history-toggle');
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    const search = screen.getByTestId('assistant-history-search');
    fireEvent.change(search, { target: { value: 'PANAMA' } });
    expect(document.querySelectorAll('.assistant-history-item')).toHaveLength(1);
    fireEvent.change(search, { target: { value: 'zzzz' } });
    expect(screen.getByText('No hay conversaciones que coincidan.')).toBeTruthy();
  });

  it('pide confirmación antes de reemplazar un borrador al editar una pregunta fallida', async () => {
    const api = new MockApi();
    vi.spyOn(api, 'query').mockRejectedValue(new ApiError(503, null, 'caído'));
    mount(assistant, api);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Pregunta original' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-error');
    const input = screen.getByLabelText('Tu pregunta') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'Borrador nuevo' } });
    fireEvent.click(screen.getByTestId('assistant-edit-question'));
    fireEvent.click(await screen.findByRole('button', { name: 'Conservar borrador' }));
    expect(input.value).toBe('Borrador nuevo');
    fireEvent.click(screen.getByTestId('assistant-edit-question'));
    fireEvent.click(await screen.findByRole('button', { name: 'Reemplazar' }));
    expect(input.value).toBe('Pregunta original');
  });

  it('numera las fuentes, enlaza los marcadores, muestra el pasaje resaltado y excluye fuentes con instrucciones', async () => {
    const api = new MockApi();
    const base = await api.query({ question: 'Canal' });
    const citation = (n: number) => ({ evidenceId: `ev-${n}`, field: 'title', passage: `Tránsito del Canal número ${n}`, title: `Titular ${n}`, url: `https://example.org/${n}` });
    const hit = (n: number, extra: Record<string, unknown> = {}) => ({ evidenceId: `ev-${n}`, kind: 'articulo', title: `Titular ${n}`, outlet: `Medio ${n}`, publishedAt: '2026-10-07T12:00:00Z', ...extra });
    vi.spyOn(api, 'query').mockResolvedValue({
      ...base, answerStatus: 'respondida', answer: 'Primer dato [1], segundo [2] y tercero [3].',
      citations: [citation(1), citation(2), citation(3)],
      hits: [hit(1), hit(2), hit(3), hit(9, { suspiciousInstructions: true, title: '[texto con instrucciones omitido]', outlet: 'Medio hostil' })],
      contradictions: [], missing: [], warnings: [], relatedTopicIds: [],
      retrieval: { ...base.retrieval, matchedTerms: ['transit', 'canal'] },
    } as unknown as Awaited<ReturnType<MockApi['query']>>);
    mount(assistant, api);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué pasa en el Canal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-answer');
    expect(screen.getByTestId('assistant-mode').textContent).toMatch(/sin modelo de IA/);
    const markers = screen.getAllByTestId('assistant-cite-marker');
    expect(markers).toHaveLength(3);
    // La tercera fuente está plegada: el marcador la abre y la enfoca.
    fireEvent.click(markers[2]!);
    await waitFor(() => expect(document.activeElement?.getAttribute('data-source-index')).toBe('3'));
    expect(screen.getByTestId('assistant-more-sources').getAttribute('data-open')).toBe('true');
    // Pasaje con términos coincidentes resaltados.
    fireEvent.click(screen.getAllByRole('button', { name: 'Pasaje citado' })[0]!);
    const marks = [...document.querySelectorAll('mark.assistant-mark')].map((item) => item.textContent);
    expect(marks).toEqual(expect.arrayContaining(['Tránsito', 'Canal']));
    // Fuente hostil: listada como excluida, sin su texto.
    const excluded = screen.getByTestId('assistant-untrusted');
    expect(excluded.textContent).toMatch(/Medio hostil/);
    expect(excluded.textContent).not.toMatch(/instrucciones omitido/);
  });

  it('continúa la conversación con el contexto estructurado, ofrece preguntas de seguimiento y permite empezar de cero', async () => {
    const api = new MockApi();
    const base = await api.query({ question: 'Desempleo' });
    const context = { snapshotId: base.snapshotId, intent: 'contexto_economico', topicIds: [], evidenceIds: ['ev-1'], countries: ['PAN'], indicators: ['SL.UEM.TOTL.ZS'], years: [2023] };
    const query = vi.spyOn(api, 'query').mockImplementation(async (request) => ({
      ...base, question: request.question, answerStatus: 'respondida', answer: 'Desempleo [1]', citations: [], hits: [], contradictions: [], missing: [], relatedTopicIds: [], warnings: [],
      resolvedQuestion: request.followUp ? 'Desempleo de Colombia en 2023' : null,
      followUpContext: context, followUpSuggestions: ['¿Y en Colombia?', '¿Cuáles son las fuentes?'],
    } as unknown as Awaited<ReturnType<MockApi['query']>>));
    mount(assistant, api);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Desempleo de Panamá en 2023' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-answer');
    expect(query.mock.calls[0]![0]).toEqual({ question: 'Desempleo de Panamá en 2023', topicId: null, searchMode: 'auto' });
    // Un seguimiento enviado desde un chip lleva el contexto estructurado, nunca el texto de la respuesta.
    fireEvent.click(await screen.findByRole('button', { name: '¿Y en Colombia?' }));
    await waitFor(() => expect(query).toHaveBeenCalledTimes(2));
    expect(query.mock.calls[1]![0]).toEqual({ question: '¿Y en Colombia?', topicId: null, followUp: context, searchMode: 'auto' });
    expect(JSON.stringify(query.mock.calls[1]![0])).not.toContain('Desempleo [1]');
    await waitFor(() => expect(screen.getAllByTestId('assistant-answer')).toHaveLength(2));
    expect(screen.getByTestId('assistant-resolved').textContent).toMatch(/Desempleo de Colombia en 2023/);
    // Solo la última respuesta ofrece continuaciones.
    expect(screen.getAllByTestId('assistant-followups')).toHaveLength(1);
    // Con el conmutador apagado la siguiente pregunta es independiente.
    fireEvent.click(screen.getByRole('checkbox', { name: /Continuar con el contexto/ }));
    fireEvent.change(screen.getByLabelText('Tu pregunta'), { target: { value: 'Inflación de México' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await waitFor(() => expect(query).toHaveBeenCalledTimes(3));
    expect(query.mock.calls[2]![0]).toEqual({ question: 'Inflación de México', topicId: null, searchMode: 'auto' });
  });

  it('marca como no leída la respuesta que llega con el panel cerrado y la limpia al volver a mirarla', async () => {
    const api = new MockApi();
    const real = await api.query({ question: 'Canal' });
    let release: (() => void) | undefined;
    vi.spyOn(api, 'query').mockImplementation(() => new Promise((resolve) => { release = () => resolve({ ...real, followUpContext: null, followUpSuggestions: [] }); }));
    const counts: number[] = [];
    function Harness() {
      const [state, setState] = useState<'open' | 'closed'>('open');
      return (
        <>
          <button type="button" onClick={() => setState(state === 'open' ? 'closed' : 'open')}>alternar-panel</button>
          <AssistantPanel state={state} onStateChange={() => {}} onClose={() => setState('closed')} onUnreadChange={(count) => counts.push(count)} seed={{ text: '', topicId: null, topicTitle: '', n: 0 }} />
        </>
      );
    }
    mount(<Harness />, api);
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué pasa en el Canal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-cancel');
    fireEvent.click(screen.getByRole('button', { name: 'alternar-panel' }));
    release?.();
    await waitFor(() => expect(counts.at(-1)).toBe(1));
    fireEvent.click(screen.getByRole('button', { name: 'alternar-panel' }));
    await screen.findByTestId('assistant-answer');
    await waitFor(() => expect(counts.at(-1)).toBe(0));
  });

  async function answeredWithSources(api: MockApi) {
    const base = await api.query({ question: 'Canal' });
    const result = {
      ...base, answerStatus: 'respondida', answer: 'TVN reporta: «Tránsito del Canal» [1]', contradictions: [], missing: [], warnings: [], relatedTopicIds: [],
      citations: [{ evidenceId: 'ev-1', field: 'title', passage: 'Tránsito del Canal', title: 'Tránsito del Canal', url: 'https://example.org/1' }],
      hits: [], followUpContext: null, followUpSuggestions: [],
    } as unknown as Awaited<ReturnType<MockApi['query']>>;
    vi.spyOn(api, 'query').mockResolvedValue(result);
    const health = await api.health();
    vi.spyOn(api, 'health').mockResolvedValue({ ...health, providers: health.providers.map((provider) => provider.name === 'gemini' ? { ...provider, available: true, reason: null } : provider) });
    return result;
  }

  async function askCanal() {
    fireEvent.change(await screen.findByLabelText('Tu pregunta'), { target: { value: 'Qué pasa en el Canal' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    await screen.findByTestId('assistant-answer');
  }

  it('redacta con IA bajo demanda, rotula el origen y conserva la respuesta por reglas', async () => {
    const api = new MockApi();
    await availableGemini(api);
    const result = await answeredWithSources(api);
    const compose = vi.spyOn(api, 'compose').mockResolvedValue({
      response: { ...result, answer: 'Respuesta redactada con IA\n- El medio reporta el tránsito [1]' }, answerMode: 'modelo', rulesAnswer: result.answer,
      provider: 'gemini', model: 'gemini-test', fallbackReason: null, fallbackDetail: null, usage: null, notices: [],
    } as unknown as Awaited<ReturnType<MockApi['compose']>>);
    mount(assistant, api);
    await askCanal();
    expect(screen.getByTestId('assistant-mode').getAttribute('data-mode')).toBe('reglas');
    fireEvent.click(screen.getByTestId('assistant-compose'));
    await waitFor(() => expect(screen.getByTestId('assistant-mode').getAttribute('data-mode')).toBe('modelo'));
    expect(compose).toHaveBeenCalledWith({ question: 'Qué pasa en el Canal', topicId: null, provider: 'gemini' }, { signal: expect.any(AbortSignal) });
    expect(screen.getByTestId('assistant-mode').textContent).toMatch(/gemini-test.*verificada por código/);
    expect(screen.getByTestId('assistant-answer-text').textContent).toMatch(/Respuesta redactada con IA/);
    expect(screen.queryByTestId('assistant-compose')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Ver la respuesta por reglas' }));
    expect(screen.getByTestId('assistant-rules-answer').textContent).toMatch(/TVN reporta/);
    expect(screen.getByTestId('assistant-announcer').textContent).toMatch(/redactada con IA/);
  });

  it('el selector del asistente muestra el estado real y envía el proveedor elegido', async () => {
    const api = new MockApi();
    const health = await api.health();
    const base = health.providers.find((provider) => provider.name === 'gemini')!;
    vi.spyOn(api, 'health').mockResolvedValue({
      ...health,
      localMode: true,
      authMode: 'local',
      providers: [
        { ...base, name: 'gemini', available: true, model: 'gemini-test' },
        { ...base, name: 'chatgpt', available: true, localOnly: true, model: 'gpt-test', signIn: 'oauth', account: 'cuenta-fixture' },
        { ...base, name: 'claude', available: false, localOnly: true, model: 'claude-test', signIn: 'cli', account: null, reason: 'Sin sesión de Claude.' },
      ],
    });
    const answer = await answeredWithSources(api);
    const compose = vi.spyOn(api, 'compose').mockResolvedValue({
      response: { ...answer, answer: 'Respuesta redactada por ChatGPT' }, answerMode: 'modelo', rulesAnswer: answer.answer,
      provider: 'chatgpt', model: 'gpt-test', fallbackReason: null, fallbackDetail: null, usage: null, notices: [],
    } as unknown as Awaited<ReturnType<MockApi['compose']>>);
    mount(assistant, api);
    await askCanal();
    const selector = await screen.findByRole('combobox', { name: /Proveedor de redacción: Gemini/ });
    await waitFor(() => expect(selector.getAttribute('aria-disabled')).toBeNull());
    expect(selector.textContent).toContain('Proveedor');
    expect(selector.textContent).toContain('Gemini');
    expect(selector.textContent).toContain('gemini-test');
    expect(selector.closest('.assistant-model-controls')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cuentas y modelos' })).toBeTruthy();
    fireEvent.click(selector);
    const listbox = await screen.findByRole('listbox');
    expect(listbox.parentElement?.classList.contains('select-popover')).toBe(true);
    expect((listbox.parentElement as HTMLElement).style.width).toBe('320px');
    fireEvent.click(await screen.findByRole('option', { name: /ChatGPT.*gpt-test/ }));
    const selectedSelector = await screen.findByRole('combobox', { name: /Proveedor de redacción: ChatGPT/ });
    fireEvent.click(selectedSelector);
    const claudeOption = await screen.findByRole('option', { name: /Claude/ });
    expect(claudeOption.getAttribute('aria-disabled')).toBeNull();
    expect(claudeOption.textContent).toMatch(/Inicia sesión con tu cuenta de Claude/);
    fireEvent.keyDown(selectedSelector, { key: 'Escape' });
    fireEvent.click(await screen.findByRole('button', { name: 'Redactar con ChatGPT' }));
    await waitFor(() => expect(compose).toHaveBeenCalledWith(
      { question: 'Qué pasa en el Canal', topicId: null, provider: 'chatgpt' }, { signal: expect.any(AbortSignal) },
    ));
  });

  it('si la redacción falla conserva la respuesta por reglas, explica el motivo y permite reintentar', async () => {
    const api = new MockApi();
    await availableGemini(api);
    const result = await answeredWithSources(api);
    vi.spyOn(api, 'compose').mockResolvedValue({
      response: result, answerMode: 'reglas', rulesAnswer: result.answer, provider: null, model: null,
      fallbackReason: 'limite_global', fallbackDetail: 'Cuota global diaria de Gemini alcanzada (20/20).', usage: null, notices: [],
    } as unknown as Awaited<ReturnType<MockApi['compose']>>);
    mount(assistant, api);
    await askCanal();
    fireEvent.click(screen.getByTestId('assistant-compose'));
    const note = await screen.findByTestId('assistant-compose-note');
    expect(note.textContent).toMatch(/límite diario compartido alcanzado.*Cuota global diaria/);
    expect(screen.getByTestId('assistant-mode').getAttribute('data-mode')).toBe('reglas');
    expect(screen.getByTestId('assistant-answer-text').textContent).toMatch(/TVN reporta/);
    expect(screen.getByTestId('assistant-compose')).toBeTruthy();
  });

  it('no ofrece redactar con IA cuando Gemini no está disponible y dice por qué', async () => {
    const api = new MockApi();
    await answeredWithSources(api);
    const health = await api.health();
    vi.spyOn(api, 'health').mockResolvedValue({ ...health, providers: [{ ...health.providers[0]!, name: 'gemini', available: false, reason: 'GEMINI_API_KEY no configurada' }] });
    mount(assistant, api);
    await askCanal();
    expect((await screen.findByTestId('assistant-compose-unavailable')).textContent).toMatch(/GEMINI_API_KEY no configurada/);
    expect(screen.queryByTestId('assistant-compose')).toBeNull();
  });

  it('permite cancelar una redacción en curso sin perder la respuesta por reglas', async () => {
    const api = new MockApi();
    await availableGemini(api);
    await answeredWithSources(api);
    vi.spyOn(api, 'compose').mockImplementation((_request, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new Error('abortada')));
    }));
    mount(assistant, api);
    await askCanal();
    fireEvent.click(screen.getByTestId('assistant-compose'));
    fireEvent.click(await screen.findByTestId('assistant-compose-cancel'));
    expect((await screen.findByTestId('assistant-compose-note')).textContent).toMatch(/redacción cancelada/);
    expect(screen.getByTestId('assistant-answer-text').textContent).toMatch(/TVN reporta/);
  });
});
