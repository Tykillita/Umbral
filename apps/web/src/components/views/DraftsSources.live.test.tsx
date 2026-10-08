// @vitest-environment jsdom
// Prueba de integración REAL de Borradores y Fuentes contra la API en marcha (UMBRAL_API_URL, por defecto
// http://127.0.0.1:8000). Opt-in: UMBRAL_LIVE_TESTS=1. Si se pide ejecutar y la API no responde, falla.
// Requiere el snapshot sintético de pruebas (contiene inflación/idaan), SQLite nueva y sin Gemini real.
// Arranque sugerido de la API: cd apps/api && UMBRAL_GEMINI_STUB=ok uv run uvicorn umbral_api.main:app --port 8000
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { HttpApi } from '../../lib/api/client';
import type { Route } from '../../lib/router';
import { AppContext } from '../context';
import { Drafts } from './Drafts';
import { Sources } from './Sources';

const BASE = (process.env.UMBRAL_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const liveTests = process.env.UMBRAL_LIVE_TESTS === '1';
const api = new HttpApi(BASE, async () => null);

beforeAll(async () => {
  if (liveTests) await api.health();
});
afterEach(cleanup);

function mount(route: Route, reviewer = 'Marta Pérez') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let name = reviewer;
  const ctx = {
    api,
    mockReason: null,
    route,
    go: () => {},
    get reviewer() {
      return name;
    },
    setReviewer: (n: string) => {
      name = n;
    },
    openAssistant: () => {},
    authMode: 'local' as const,
  };
  return render(
    <QueryClientProvider client={qc}>
      <AppContext.Provider value={ctx}>{route.view === 'fuentes' ? <Sources /> : <Drafts />}</AppContext.Provider>
    </QueryClientProvider>,
  );
}

async function pickTopic(needle: string): Promise<string> {
  const t = await api.topics({ limit: 50 });
  const hit = t.items.find((i) => i.title.toLowerCase().includes(needle));
  if (!hit) throw new Error(`tema no encontrado: ${needle}`);
  return hit.id;
}

describe.runIf(liveTests)('Fuentes y evaluación (API real, fixture controlado)', () => {
  it('muestra snapshot, integridad, catálogo, calidad y métricas «sin ejecutar»', async () => {
    mount({ view: 'fuentes' });
    const id = await screen.findByTestId('sources-snapshot-id');
    expect(id.textContent).toMatch(/^\d{8}-[0-9a-f]{8}$/);
    await screen.findByTestId('snapshot-provisional');
    expect(screen.getByTestId('integrity-status').textContent).toMatch(/verificado/);
    await waitFor(() => expect(screen.getAllByTestId('source-row').length).toBeGreaterThan(0));
    expect(screen.getByTestId('quality-report')).toBeTruthy();
    const snap = await api.snapshot();
    if (snap.metrics === null) expect((await screen.findByTestId('metrics-empty')).textContent).toMatch(/Sin ejecutar/);
    expect(screen.getByTestId('metrics-table')).toBeTruthy();
  });
});

describe.runIf(liveTests)('Borradores (API real, fixture controlado)', () => {
  it('lista temas cuando no hay topicId', async () => {
    mount({ view: 'borradores', topicId: null });
    await waitFor(() => expect(screen.getAllByTestId('draft-pick-topic').length).toBeGreaterThan(1));
  });

  it('recorrido: generar, etiqueta de origen, validación, editar/guardar, revisión, 409 y exportar', async () => {
    const topicId = await pickTopic('inflación');
    mount({ view: 'borradores', topicId });
    await screen.findByTestId('draft-view');
    expect((await screen.findByTestId('headline-only-notice')).textContent).toMatch(/titular\/metadatos/);

    // sin borrador previo (base SQLite nueva) o con uno: generamos
    fireEvent.click(await screen.findByTestId('draft-generate'));
    const label = await screen.findByTestId('draft-origin-label', {}, { timeout: 15_000 });
    expect(['modelo', 'recuperado', 'plantilla']).toContain(label.getAttribute('data-mode'));
    const brief = (await screen.findByTestId('draft-brief')) as HTMLTextAreaElement;
    expect(brief.value).toMatch(/titular\/metadatos/);
    const val = await screen.findByTestId('draft-validation');
    expect(val.getAttribute('data-ok')).toBe('true');
    expect(within(val).getByTestId('draft-factual-coverage').textContent).toMatch(/100 %/);
    const claims = screen.getAllByTestId('draft-claim');
    expect(claims.some((c) => ['hecho', 'declaracion'].includes(c.getAttribute('data-claim-type') ?? ''))).toBe(true);
    expect(screen.getAllByTestId('draft-claim-citation').length).toBeGreaterThan(0);

    // editar y guardar (expectedVersion lo pone la vista)
    fireEvent.change(brief, { target: { value: `${brief.value} Nota del editor.` } });
    expect(screen.getByTestId('draft-dirty')).toBeTruthy();
    fireEvent.click(screen.getByTestId('draft-save'));
    await screen.findByTestId('draft-saved');

    // pasar a revisión con responsable
    const before = await api.getCase(`case-${topicId}`);
    const st = screen.getByTestId('review-status');
    expect(st.getAttribute('data-version')).toBe(String(before.version));
    fireEvent.click(screen.getByTestId('review-action-en_revision'));
    await waitFor(() => expect(screen.getByTestId('review-status').getAttribute('data-status')).toBe('en_revision'));
    expect(screen.getByTestId('review-history').textContent).toMatch(/Marta Pérez/);

    // conflicto 409: otra persona avanza el caso por fuera; esta vista aún cree tener la versión anterior
    const cur = await api.getCase(`case-${topicId}`);
    await api.review(cur.caseId, { expectedVersion: cur.version, status: 'requiere_evidencia', reviewer: 'Otra Persona', comment: 'Falta fuente.' });
    fireEvent.change(screen.getByTestId('review-comment'), { target: { value: 'mi comentario' } });
    fireEvent.click(screen.getByTestId('review-action-descartado'));
    const conflict = await screen.findByTestId('review-conflict');
    expect(conflict.textContent).toMatch(/Conflicto de versión/);
    expect((screen.getByTestId('review-comment') as HTMLTextAreaElement).value).toBe('mi comentario');
    const latest = await api.getCase(cur.caseId);
    expect(latest.status).toBe('requiere_evidencia'); // no se sobrescribió

    // recargar caso y exportar
    await act(async () => {
      fireEvent.click(screen.getByTestId('reload-case'));
    });
    await waitFor(() => expect(screen.getByTestId('review-status').getAttribute('data-status')).toBe('requiere_evidencia'));
    fireEvent.click(screen.getByTestId('export-markdown'));
    expect((await screen.findByTestId('export-preview')).textContent).toMatch(/# Ficha:/);
  });

  it('con evidencia insuficiente no deja aprobar sin confirmación del revisor', async () => {
    const topicId = await pickTopic('idaan');
    mount({ view: 'borradores', topicId });
    fireEvent.click(await screen.findByTestId('draft-generate'));
    await screen.findByTestId('draft-origin-label', {}, { timeout: 15_000 });
    fireEvent.click(screen.getByTestId('review-action-en_revision'));
    await waitFor(() => expect(screen.getByTestId('review-status').getAttribute('data-status')).toBe('en_revision'));
    const approve = screen.getByTestId('review-action-aprobado_como_borrador') as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    expect(approve.title).toMatch(/insuficiente/i);
    expect(screen.getByTestId('topic-needs-investigation').textContent).toMatch(/no habilita publicación/);
  });
});
