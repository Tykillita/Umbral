import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { IDBFactory, IDBObjectStore } from 'fake-indexeddb';
import { BrowserWorkspaceApi } from './browserWorkspace';
import { BrowserWorkspace, parseWorkspace } from './workspace';
import { HttpApi } from './client';
import { MockApi } from '../mock/mockApi';
import { MOCK_HEALTH, MOCK_RULES, MOCK_SPECS } from '../mock/data';
import type { CaseView, DraftRecord, ImpactRequest, TopicDetail } from './types';

let detail: TopicDetail, draft: DraftRecord, factory: IDBFactory, snapshot: string;
let calls: { path: string; method: string; body: Record<string, unknown> | null; headers: Record<string,string> }[];
const spaces: BrowserWorkspace[] = [];
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
beforeAll(async () => {
  const mock = new MockApi();
  detail = await mock.topic(MOCK_SPECS[0]!.id);
  draft = (await mock.createDraft(detail.summary.id, 'plantilla')).draft;
});
beforeEach(() => {
  factory = new IDBFactory(); snapshot = detail.snapshotId; calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    const path = new URL(url, 'http://localhost').pathname;
    const body = options.body ? JSON.parse(String(options.body)) as Record<string, unknown> : null;
    calls.push({ path, method: options.method ?? 'GET', body, headers: options.headers as Record<string,string> });
    if (path.endsWith('/health')) return json({ ...MOCK_HEALTH, snapshotId: snapshot, authMode: 'public', persistence: 'none' });
    if (path.endsWith('/rules')) return json(MOCK_RULES);
    if (path.includes('/public/topics/')) return json(detail);
    if (path.endsWith('/public/drafts')) return json({ draft: { ...draft, draftId: 'd_' + crypto.randomUUID() }, notices: ['Fixture de adaptador.'], evidence: { articles: detail.articles, officialContext: detail.officialContext, snapshotId: snapshot, topicId: detail.summary.id } });
    if (path.endsWith('/public/validate')) {
      const c = body?.case as CaseView | undefined;
      if (c) {
        const review = body!.review as { status: CaseView['status']; reviewer: string }, at = new Date().toISOString();
        return json({ package: null, validation: null, case: { ...c, status: review.status, statusLabel: 'En revisión', version: c.version + 1,
          currentDraft: c.drafts.at(-1) ?? null, persisted: false, reviewer: review.reviewer, updatedAt: at, createdAt: c.createdAt ?? at,
          allowedTransitions: ['requiere_evidencia','aprobado_como_borrador','descartado'],
          history: [{ version: c.version + 1, at, kind: 'revision', actor: review.reviewer, fromStatus: c.status, toStatus: review.status, comment: null, rulesVersion: c.rulesVersion, draftNumber: c.drafts.at(-1)?.number ?? null }] } });
      }
      return json({ package: body?.package, validation: draft.validation, case: null });
    }
    if (path.endsWith('/public/agenda')) {
      if ((body?.context as { snapshotId: string }).snapshotId !== snapshot) return json({ code: 'conflicto_de_version', message: 'Corte actualizado.', details: { currentSnapshotId: snapshot } }, 409);
      return json({ snapshotId: snapshot, items: [detail.summary] });
    }
    throw new Error('Solicitud inesperada: ' + path);
  }));
});
afterEach(async () => { for (const space of spaces.splice(0)) await space.close(); vi.unstubAllGlobals(); });
function api(name = 'workspace-test', ownFactory = factory) {
  const space = new BrowserWorkspace(ownFactory, name); spaces.push(space);
  return new BrowserWorkspaceApi(new HttpApi('', async () => null), space);
}
const impact = (): ImpactRequest => ({ expectedVersion: 0, level: 'alto', justification: 'Impacto editorial sustentado con fuentes del tema.', author: 'Editora privada', reason: 'Revisión de impacto', evidenceIds: [detail.articles[0]!.id] });

describe('trabajo privado del navegador', () => {
  it('recupera versiones tras recarga sin Authorization ni escrituras de casos remotas', async () => {
    const one = api(); await one.initialize();
    const made = await one.createDraft(detail.summary.id, 'plantilla');
    const edited = await one.saveDraft(made.case.caseId, { expectedVersion: 1, editor: 'Editora', brief: 'Texto propio.' });
    expect(edited.version).toBe(2); expect(edited.drafts).toHaveLength(2);
    expect(edited.drafts[0]!.package.brief).toBe(draft.package.brief);
    expect(edited.currentDraft?.previousDraftId).toBe(made.draft.draftId);
    const reloaded = api(); await reloaded.initialize();
    expect((await reloaded.getCase(made.case.caseId)).currentDraft?.package.brief).toBe('Texto propio.');
    expect(calls.every((call) => !call.headers.Authorization)).toBe(true);
    expect(calls.filter((call) => call.method !== 'GET').every((call) => call.path.includes('/public/'))).toBe(true);
  });
  it('dos navegadores mantienen casos y pesos independientes', async () => {
    const one = api('one', new IDBFactory()), two = api('two', new IDBFactory());
    await Promise.all([one.initialize(), two.initialize()]);
    await one.createDraft(detail.summary.id, 'plantilla');
    await one.updateRules({ expectedVersion: 0, weights: { R: 40, I: 20, U: 20, N: 10, E: 10 }, author: 'A', reason: 'Priorizar relevancia' });
    expect(await one.savedCases()).toHaveLength(1); expect(await two.savedCases()).toHaveLength(0);
    expect((await two.rules()).weights.R).toBe(30);
  });
  it('dos pestañas compiten por la misma versión: sólo una transacción guarda', async () => {
    const one = api(), two = api(); await Promise.all([one.initialize(), two.initialize()]);
    const results = await Promise.allSettled([one.setImpact(detail.summary.id, impact()), two.setImpact(detail.summary.id, impact())]);
    expect(results.filter((result) => result.status === 'fulfilled')).toHaveLength(1);
    expect(results.find((result) => result.status === 'rejected')).toMatchObject({ reason: { status: 409, details: { currentVersion: 1, expectedVersion: 0 } } });
    expect((await one.getCase(detail.case.caseId)).history).toHaveLength(1);
  });
  it('BroadcastChannel notifica cambios confirmados a otra pestaña', async () => {
    const one = api(), two = api(); await Promise.all([one.initialize(), two.initialize()]);
    const notified = vi.fn(); const unsubscribe = two.subscribe(notified);
    await one.setImpact(detail.summary.id, impact());
    await vi.waitFor(() => expect(notified).toHaveBeenCalled());
    expect((await two.getCase(detail.case.caseId)).version).toBe(1); unsubscribe();
  });
  it('pesos usan CAS y conservan autoría privada sin enviarla al ranking', async () => {
    const one = api(), two = api(); await Promise.all([one.initialize(), two.initialize()]);
    const body = { expectedVersion: 0, weights: { R: 40, I: 20, U: 20, N: 10, E: 10 }, author: 'Autora privada', reason: 'Priorizar relevancia' };
    const results = await Promise.allSettled([one.updateRules(body), two.updateRules(body)]);
    expect(results.filter((result) => result.status === 'fulfilled')).toHaveLength(1);
    expect((await one.rules()).history[0]).toMatchObject({ author: body.author, reason: body.reason, version: 1 });
    await one.setImpact(detail.summary.id, impact()); await one.topics({});
    const context = calls.at(-1)!.body!.context as { topicOverrides: { impact: { author: string } }[] };
    expect(context.topicOverrides[0]!.impact.author).toBe('dispositivo');
  });
  it('conserva evidencia original tras actualizar snapshot y permite editar el archivo', async () => {
    const one = api(); await one.initialize(); const made = await one.createDraft(detail.summary.id, 'plantilla');
    snapshot = '20261008-next'; await one.health();
    const archived = await one.topic(detail.summary.id);
    expect(archived.snapshotId).toBe(detail.snapshotId); expect(archived.articles).toEqual(detail.articles);
    const edited = await one.saveDraft(made.case.caseId, { expectedVersion: 1, editor: 'Editor', brief: 'Edición del archivo.' });
    expect(edited.snapshotId).toBe(detail.snapshotId);
    const markdown = await one.exportCase(made.case.caseId);
    expect(markdown.markdown).toContain(detail.articles[0]!.id); expect(markdown.snapshotId).toBe(detail.snapshotId);
  });
  it('refresca una sola vez el contexto ante conflicto de snapshot', async () => {
    const one = api(); await one.initialize(); snapshot = '20261008-next';
    expect((await one.topics({})).snapshotId).toBe(snapshot);
    expect(calls.filter((call) => call.path.endsWith('/public/agenda'))).toHaveLength(2);
  });
  it('revisión transmite sólo draft vigente y fusiona todos los eventos locales', async () => {
    const one = api(); await one.initialize(); const made = await one.createDraft(detail.summary.id, 'plantilla');
    await one.saveDraft(made.case.caseId, { expectedVersion: 1, editor: 'Nombre privado', brief: 'Edición humana.' });
    const reviewed = await one.review(made.case.caseId, { expectedVersion: 2, reviewer: 'Revisora', status: 'en_revision' });
    expect(reviewed.version).toBe(3); expect(reviewed.history).toHaveLength(3); expect(reviewed.drafts).toHaveLength(2);
    expect(reviewed.drafts[1]!.editedBy).toBe('Nombre privado');
    const transient = calls.at(-1)!.body!.case as CaseView;
    expect(transient.history).toEqual([]); expect(transient.drafts).toHaveLength(1); expect(transient.drafts[0]!.editedBy).toBeNull();
  });
  it('copia JSON roundtrip e import idéntico conservan historia sin nuevas versiones', async () => {
    const original = api('original'), restored = api('restored');
    await original.initialize(); await original.createDraft(detail.summary.id, 'plantilla');
    const backup = JSON.parse(JSON.stringify(await original.exportWorkspace()));
    expect(await restored.importWorkspace(backup)).toEqual({ imported: 1 });
    expect(await restored.importWorkspace(backup)).toEqual({ imported: 0 });
    expect((await restored.exportWorkspace()).cases).toEqual(backup.cases);
  });
  it('import con conflicto o historial incorrecto no hace cambios parciales', async () => {
    const one = api(); await one.initialize(); await one.createDraft(detail.summary.id, 'plantilla');
    const backup = await one.exportWorkspace(), before = structuredClone(backup.cases);
    backup.cases[0]!.case.reviewer = 'Otra versión';
    await expect(one.importWorkspace(backup)).rejects.toMatchObject({ status: 409 });
    expect((await one.exportWorkspace()).cases).toEqual(before);
    backup.cases[0]!.case.version++;
    expect(() => parseWorkspace(backup)).toThrow(/historial/); expect((await one.exportWorkspace()).cases).toEqual(before);
  });
  it('almacenamiento no disponible nunca declara un guardado exitoso', async () => {
    const unavailable = new BrowserWorkspace(undefined);
    await expect(unavailable.read()).rejects.toMatchObject({ code: 'almacenamiento_no_disponible', message: expect.stringContaining('no se guardó') });
    await unavailable.close();
  });
});

it('un fallo al abrir IndexedDB explica que el navegador no guardó', async () => {
  const blocked = new BrowserWorkspace({ open: () => { throw new DOMException('Storage denied', 'SecurityError'); } } as unknown as IDBFactory);
  await expect(blocked.read()).rejects.toMatchObject({ code: 'almacenamiento_no_disponible' }); await blocked.close();
});
it('la copia rechaza URL peligrosa, resumen inválido y pesos sin historial', async () => {
  const one = api(); await one.initialize(); await one.createDraft(detail.summary.id, 'plantilla');
  const backup = await one.exportWorkspace(), unsafe = structuredClone(backup), invalid = structuredClone(backup);
  unsafe.cases[0]!.detail.articles[0]!.url = 'javascript:malicious()';
  expect(() => parseWorkspace(unsafe)).toThrow(/URL/);
  invalid.cases[0]!.detail.summary.evidenceStatus = 'unknown' as never;
  expect(() => parseWorkspace(invalid)).toThrow(/resumen/);
  backup.rules.version = 2; expect(() => parseWorkspace(backup)).toThrow(/historial de pesos/);
});
it('un conflicto posterior revierte también los casos nuevos del mismo import', async () => {
  const one = api(); await one.initialize(); await one.createDraft(detail.summary.id, 'plantilla');
  const backup = await one.exportWorkspace(), mock = new MockApi(), secondId = MOCK_SPECS[1]!.id;
  await mock.createDraft(secondId, 'plantilla'); const secondDetail = await mock.topic(secondId);
  backup.cases.unshift({ case: secondDetail.case, detail: secondDetail });
  backup.cases[1]!.case.reviewer = 'Conflicto después de otro caso';
  await expect(one.importWorkspace(backup)).rejects.toMatchObject({ status: 409 });
  expect(await one.savedCases()).toHaveLength(1);
});
it('cuota agotada aborta el cambio y conserva intactos los casos anteriores', async () => {
  const one = api(); await one.initialize();
  const store = vi.spyOn(IDBObjectStore.prototype, 'put').mockImplementationOnce(() => { throw new DOMException('Quota', 'QuotaExceededError'); });
  try { await expect(one.setImpact(detail.summary.id, impact())).rejects.toMatchObject({ code: 'almacenamiento_lleno', message: expect.stringContaining('no se guardó') }); }
  finally { store.mockRestore(); }
  expect(await one.savedCases()).toHaveLength(0);
});
it('la copia conserva justificaciones y citas de todos los impactos editoriales', async () => {
  const original = api('impact-original'), restored = api('impact-restored'); await original.initialize();
  const first = await original.setImpact(detail.summary.id, impact());
  await original.setImpact(detail.summary.id, { ...impact(), expectedVersion: first.version, level: 'medio', reason: 'Segunda revisión de impacto' });
  const backup = await original.exportWorkspace(); expect(backup.cases[0]!.impactHistory).toHaveLength(2);
  await restored.importWorkspace(JSON.parse(JSON.stringify(backup)));
  const copied = await restored.exportWorkspace(); expect(copied.cases[0]!.impactHistory).toEqual(backup.cases[0]!.impactHistory);
  expect(copied.cases[0]!.impactHistory![0]!.reason).toBe('Revisión de impacto');
});