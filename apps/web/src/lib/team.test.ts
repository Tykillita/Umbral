import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { config } from './config';
import { chooseRole } from './session';
import {
  labelsForSession,
  latestLabels,
  readTeam,
  retrySharing,
  sharedConfiguration,
  storeDecision,
  storeLabel,
  type TeamDecision,
} from './team';

beforeEach(() => {
  localStorage.clear();
  config.supabase.url = '';
  config.supabase.anonKey = '';
});
afterEach(() => vi.restoreAllMocks());
const sheetHash = 'a'.repeat(64);
const labelBody = {
  snapshotId: '20261008-test',
  sheetHash,
  type: 'topic' as const,
  itemId: 'article-1',
  value: 'economia',
  comment: 'Juicio humano explícito',
};
function decision(): TeamDecision {
  return {
    eventId: crypto.randomUUID(),
    snapshotId: '20261008-test',
    topicId: 't1',
    caseId: 'c1',
    caseVersion: 1,
    status: 'en_revision',
    ...chooseRole('editor', null),
    title: 'Titular citado',
    comment: 'Verificar cifras',
    createdAt: new Date().toISOString(),
  };
}
describe('cola de decisiones y etiquetas humanas', () => {
  it('conserva versiones y distingue el corte y la huella de las hojas', async () => {
    const session = chooseRole('juror', null);
    const first = await storeLabel(session, labelBody);
    await storeLabel(session, { ...labelBody, value: 'turismo' });
    await storeLabel(session, { ...labelBody, snapshotId: '20261009-new', value: 'regulacion' });
    const labels = readTeam().labels;
    expect(labels).toHaveLength(3);
    expect(first.role).toBe('juror');
    expect(first.labelMethod).toBe('human');
    expect(
      latestLabels(labels, session.sessionId).get(`20261008-test:${sheetHash}:topic:article-1`)?.value,
    ).toBe('turismo');
    expect(readTeam().published).toEqual([]);
  });
  it('exporta solo las respuestas de la sesión para mantener ciega la hoja ajena', async () => {
    const reviewer = chooseRole('reviewer', null), juror = chooseRole('juror', null);
    await storeLabel(reviewer, labelBody);
    await storeLabel(juror, { ...labelBody, value: 'turismo' });
    expect(labelsForSession(readTeam().labels, juror.sessionId).map((label) => label.value)).toEqual(['turismo']);
    expect(labelsForSession(readTeam().labels, undefined)).toEqual([]);
  });
  it('rechaza una respuesta automática y un valor fuera del contrato', async () => {
    const session = chooseRole('producer', null);
    await expect(storeLabel(session, { ...labelBody, value: 'prediccion' })).rejects.toThrow(/formato/);
    expect(readTeam().labels).toHaveLength(0);
  });
  it('un fallo de almacenamiento no dice que la etiqueta se guardó', async () => {
    const session = chooseRole('reviewer', null);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    await expect(storeLabel(session, labelBody)).rejects.toThrow(/No se pudo guardar/);
  });
  it('reintenta la misma identidad tras un fallo y confirma duplicados sin editar filas', async () => {
    config.supabase.url = 'https://team.supabase.co';
    config.supabase.anonKey = 'sb_publishable_fixture';
    const entry = decision();
    await storeDecision(entry);
    let saved: Record<string, unknown> | undefined;
    const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
      if (!saved) {
        saved = JSON.parse(String(init?.body));
        throw new Error('La conexión terminó después de insertar');
      }
      if (init?.method === 'POST') {
        expect(JSON.parse(String(init.body)).event_id).toBe(entry.eventId);
        return new Response('[]', { status: 201 });
      }
      return new Response(JSON.stringify([{ ...saved, created_at: '2026-10-08T20:00:00Z' }]), {
        status: 200,
      });
    });
    await expect(retrySharing()).rejects.toThrow(/conexión/);
    expect(readTeam().published).toEqual([]);
    expect(await retrySharing()).toEqual({ count: 1 });
    expect(readTeam().published).toEqual([entry.eventId]);
    expect(await retrySharing()).toEqual({ count: 0 });
    expect(fetcher.mock.calls.map(([, init]) => init?.method)).toEqual(['POST', 'POST', 'GET']);
  });
  it('no declara compartida una respuesta que no confirma el contenido', async () => {
    config.supabase.url = 'https://team.supabase.co';
    config.supabase.anonKey = 'sb_publishable_fixture';
    await storeDecision(decision());
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('[{"status":"descartado"}]', { status: 201 }),
    );
    await expect(retrySharing()).rejects.toThrow(/no confirmó/);
    expect(readTeam().published).toEqual([]);
  });
  it('rechaza claves secretas y el fallback sin configuración no hace llamadas', async () => {
    expect(sharedConfiguration()).toBeNull();
    const fetcher = vi.spyOn(globalThis, 'fetch');
    await storeDecision(decision());
    await expect(retrySharing()).rejects.toThrow(/sin configurar|no está configurada/);
    expect(fetcher).not.toHaveBeenCalled();
    config.supabase.url = 'https://team.supabase.co';
    config.supabase.anonKey = 'sb_secret_not_public';
    expect(() => sharedConfiguration()).toThrow(/pública anon/);
  });
});
