// Estados de interfaz con fixtures explícitos. La API real se verifica aparte con scripts/verify-ui.py.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { Route } from '../lib/router';
import { ApiError } from '../lib/api/client';
import { MockApi } from '../lib/mock/mockApi';
import { AppContext } from './context';
import { Agenda } from './views/Agenda';
import { Drafts } from './views/Drafts';
import { Assistant } from './Assistant';

beforeAll(() => { Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true }); });
afterEach(cleanup);

function mount(ui: ReactNode, api = new MockApi(), route: Route = { view: 'agenda' }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AppContext.Provider value={{ api, route, go: vi.fn(), mockReason: 'fixture de prueba', reviewer: '', setReviewer: vi.fn(), openAssistant: vi.fn(), authMode: 'local' }}>
        {ui}
      </AppContext.Provider>
    </QueryClientProvider>,
  );
}

const assistant = <Assistant open onClose={() => {}} seed={{ text: '', n: 0 }} />;

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
    const input = screen.getByLabelText('Tu pregunta');
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
    fireEvent.click(screen.getByLabelText('Limitar a la ficha abierta'));
    fireEvent.change(screen.getByLabelText('Tu pregunta'), { target: { value: 'Qué falta verificar' } });
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Reintenta en 20 s/);
    expect(query).toHaveBeenCalledWith({ question: 'Qué falta verificar', topicId: 'topic-test' });
    expect(screen.getByTestId('assistant-turn').textContent).toMatch(/Qué falta verificar/);
  });

  it('el panel móvil conserva Tab dentro del diálogo y devuelve el foco al cerrarse', async () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const onClose = vi.fn();
    const { unmount } = mount(<Assistant open modal onClose={onClose} seed={{ text: '', n: 0 }} />);
    const input = screen.getByLabelText('Tu pregunta');
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
    const input = screen.getByLabelText('Tu pregunta');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(query).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: 'Canal Panamá' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(query).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(query).toHaveBeenCalledOnce());
    await screen.findByTestId('assistant-answer');
  });
});
