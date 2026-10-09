import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { AppContext, type AppCtx } from './context';
import { Etiquetar } from './views/Etiquetar';
import { Mesa } from './views/Mesa';
import { Ficha } from './views/Ficha';
import { Drafts } from './views/Drafts';
import { MockApi } from '../lib/mock/mockApi';
import { chooseRole, type DemoRole } from '../lib/session';
import { config } from '../lib/config';
import { readTeam, storeDecision, storeLabel } from '../lib/team';
import type { LabelSheets } from '../lib/labelSheets';

const sheets: LabelSheets = {
  version: 1,
  snapshotId: '20261008-test',
  sheetHash: 'a'.repeat(64),
  topics: [
    {
      id: 'a1',
      text: 'Titular para juicio humano',
      outlet: 'Medio original',
      url: 'https://example.com/article',
      publishedAt: '2026-10-08T12:00:00Z',
      detectedAt: '2026-10-08T12:00:00Z',
    },
  ],
  pairs: [],
  claims: [
    {
      id: 'c1',
      text: 'La frase afirma dos cantidades.',
      citations: [
        {
          evidenceId: 'a1',
          field: 'title',
          passage: null,
          title: 'Primera fuente citada',
          outlet: 'Medio A',
          url: null,
          publishedAt: null,
          detectedAt: null,
        },
        {
          evidenceId: 'a2',
          field: 'title',
          passage: 'Otro dato reportado',
          title: 'Segunda fuente citada',
          outlet: 'Medio B',
          url: null,
          publishedAt: null,
          detectedAt: null,
        },
      ],
    },
  ],
};
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { value: vi.fn(), configurable: true });
  Object.defineProperty(window, 'matchMedia', {
    value: vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    configurable: true,
  });
});
beforeEach(() => {
  localStorage.clear();
  config.supabase.url = '';
  config.supabase.anonKey = '';
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function mount(
  ui: ReactNode,
  role: DemoRole = 'juror',
  api = new MockApi(),
  route: AppCtx['route'] = { view: 'etiquetar' },
  session = chooseRole(role, null),
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  client.setQueryData(['label-sheets'], sheets);
  const ctx: AppCtx = {
    api,
    route,
    go: vi.fn(),
    toast: null,
    showToast: vi.fn(),
    dismissToast: vi.fn(),
    mockReason: 'fixture explícito',
    reviewer: session.labeler,
    setReviewer: vi.fn(),
    openAssistant: vi.fn(),
    authMode: 'public',
    session,
  };
  render(
    <QueryClientProvider client={client}>
      <AppContext.Provider value={ctx}>{ui}</AppContext.Provider>
    </QueryClientProvider>,
  );
  return { ctx, client };
}
it('mantiene ciego el primer juicio y permite al Jurado etiquetar y revisar su respuesta', async () => {
  const other = chooseRole('reviewer', null),
    session = chooseRole('juror', null);
  await storeLabel(other, {
    snapshotId: sheets.snapshotId,
    sheetHash: sheets.sheetHash,
    type: 'topic',
    itemId: 'a1',
    value: 'turismo',
    comment: 'Juicio previo ajeno',
  });
  mount(<Etiquetar />, 'juror', new MockApi(), { view: 'etiquetar' }, session);
  await screen.findByText('Titular para juicio humano');
  expect(screen.queryByTestId('label-own-response')).toBeNull();
  expect(screen.queryByTestId('label-team-response')).toBeNull();
  expect(screen.queryByText('Juicio previo ajeno')).toBeNull();
  fireEvent.change(screen.getByLabelText('Comentario opcional'), {
    target: { value: 'Comentario del jurado' },
  });
  fireEvent.click(screen.getByTestId('etiqueta-economia'));
  expect((await screen.findByTestId('label-own-response')).textContent).toContain('Comentario del jurado');
  expect(screen.getByTestId('label-team-response')).toBeTruthy();
  const saved = readTeam().labels.find((label) => label.sessionId === session.sessionId)!;
  expect(saved).toMatchObject({
    role: 'juror',
    labelMethod: 'human',
    snapshotId: sheets.snapshotId,
    sheetHash: sheets.sheetHash,
    value: 'economia',
  });
  fireEvent.click(screen.getByTestId('etiqueta-regulacion'));
  await waitFor(() =>
    expect(readTeam().labels.filter((label) => label.sessionId === session.sessionId)).toHaveLength(2),
  );
});
it('muestra todas las citas de una afirmación y permite guardar No sé', async () => {
  mount(<Etiquetar />);
  fireEvent.click(await screen.findByTestId('etiquetar-modo-claim'));
  expect(screen.getByText('Primera fuente citada')).toBeTruthy();
  expect(screen.getByText('Segunda fuente citada')).toBeTruthy();
  fireEvent.click(screen.getByTestId('etiqueta-no_se'));
  await waitFor(() => expect(readTeam().labels[0]).toMatchObject({ type: 'claim', value: 'no_se' }));
});
it('conserva la etiqueta local e informa pendiente cuando falla Supabase', async () => {
  config.supabase.url = 'https://team.supabase.co';
  config.supabase.anonKey = 'sb_publishable_fixture';
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Conexión interrumpida'));
  mount(<Etiquetar />);
  fireEvent.click(await screen.findByTestId('etiqueta-no_se'));
  await screen.findByText('Etiqueta guardada en este navegador; sigue pendiente de compartir.');
  expect(readTeam().labels).toHaveLength(1);
  expect(readTeam().published).toEqual([]);
  expect(screen.getByTestId('team-status').textContent).toMatch(/1 entradas pendientes/);
});
it('la mesa separa un mismo caso en cortes distintos y no enlaza el corte antiguo', async () => {
  const session = chooseRole('editor', null);
  for (const [snapshotId, status, title] of [
    ['20261007-old', 'en_revision', 'Caso archivado'],
    ['20261008-current', 'requiere_evidencia', 'Caso vigente'],
  ] as const) {
    await storeDecision({
      eventId: crypto.randomUUID(),
      snapshotId,
      caseId: 'same-case',
      topicId: 'same-topic',
      caseVersion: 1,
      status,
      ...session,
      title,
      comment: 'Revisar',
      createdAt: snapshotId === '20261007-old' ? '2026-10-07T12:00:00Z' : '2026-10-08T12:00:00Z',
    });
  }
  const api = new MockApi(),
    health = await api.health();
  vi.spyOn(api, 'health').mockResolvedValue({ ...health, snapshotId: '20261008-current' });
  const { ctx } = mount(<Mesa />, 'editor', api, { view: 'mesa' }, session);
  await screen.findByTestId('mesa-column-en_revision');
  await waitFor(() => expect(screen.getAllByText('Caso archivado')).toHaveLength(2));
  expect(screen.queryByRole('button', { name: 'Caso archivado' })).toBeNull();
  fireEvent.click(screen.getAllByRole('button', { name: 'Caso vigente' })[0]!);
  expect(ctx.go).toHaveBeenCalledWith({ view: 'ficha', topicId: 'same-topic' });
});
it.each(['producer', 'reviewer'] as DemoRole[])(
  'oculta impacto y agenda al rol %s en la ficha',
  async (role) => {
    mount(<Ficha />, role, new MockApi(), { view: 'ficha', topicId: 'tema-mock-001' });
    await screen.findByTestId('ficha');
    expect(screen.queryByTestId('impact-form')).toBeNull();
    expect(screen.queryByText('Volver a la agenda')).toBeNull();
  },
);
it('Editor decide desde Ficha; Productor edita sin aprobar; Jurado edita y aprueba', async () => {
  const api = new MockApi();
  await api.createDraft('tema-mock-001', 'plantilla');
  mount(<Ficha />, 'editor', api, { view: 'ficha', topicId: 'tema-mock-001' });
  await screen.findByTestId('review-panel');
  expect(screen.queryByTestId('go-drafts')).toBeNull();
  cleanup();
  mount(<Drafts />, 'producer', api, { view: 'borradores', topicId: 'tema-mock-001' });
  await screen.findByTestId('draft-title');
  expect(screen.queryByTestId('review-panel')).toBeNull();
  cleanup();
  mount(<Drafts />, 'juror', api, { view: 'borradores', topicId: 'tema-mock-001' });
  fireEvent.change(await screen.findByTestId('draft-title'), {
    target: { value: 'Título revisado por el jurado' },
  });
  fireEvent.click(screen.getByTestId('draft-save'));
  await screen.findByTestId('draft-saved');
  expect(screen.getByTestId('review-panel')).toBeTruthy();
});
