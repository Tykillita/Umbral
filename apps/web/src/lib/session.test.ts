import { beforeEach, describe, expect, it, vi } from 'vitest';
import { canPerform, canView, chooseRole, defaultRoute, readSession, type DemoRole } from './session';
import { roleApi } from './roleApi';
import { MockApi } from './mock/mockApi';
import { readTeam } from './team';
import { config } from './config';

beforeEach(() => {
  localStorage.clear();
  config.supabase.url = '';
  config.supabase.anonKey = '';
});
describe('roles públicos de demostración', () => {
  it.each([
    ['editor', ['agenda', 'ficha', 'fuentes', 'mesa', 'etiquetar']],
    ['producer', ['ficha', 'borradores', 'fuentes', 'etiquetar']],
    ['reviewer', ['ficha', 'borradores', 'fuentes', 'mesa', 'etiquetar']],
    ['juror', ['agenda', 'ficha', 'borradores', 'fuentes', 'mesa', 'etiquetar']],
  ] as const)('limita el recorrido de %s', (role, views) => {
    for (const view of ['agenda', 'ficha', 'borradores', 'fuentes', 'mesa', 'etiquetar'] as const)
      expect(canView(role, view)).toBe((views as readonly string[]).includes(view));
    expect(canView(role, defaultRoute(role).view)).toBe(true);
  });
  it('cambiar de rol conserva la identidad de sesión y los borradores previos', () => {
    localStorage.setItem('umbral.previousDraft', 'conservar');
    const editor = chooseRole('editor', null),
      juror = chooseRole('juror', editor);
    expect(juror.sessionId).toBe(editor.sessionId);
    expect(readSession()).toEqual(juror);
    expect(localStorage.getItem('umbral.previousDraft')).toBe('conservar');
    expect(canPerform('juror', 'editDraft')).toBe(true);
    expect(canPerform('juror', 'label')).toBe(true);
  });
  it('protege acciones directas y conserva los métodos síncronos de suscripción', async () => {
    const api = new MockApi(),
      create = vi.spyOn(api, 'createDraft'),
      rules = vi.spyOn(api, 'updateRules');
    const editor = roleApi(api, chooseRole('editor', null), vi.fn());
    await expect(editor.createDraft('tema-mock-001')).rejects.toMatchObject({ status: 403 });
    expect(create).not.toHaveBeenCalled();
    const producer = roleApi(api, chooseRole('producer', null), vi.fn());
    await expect(producer.updateRules({} as never)).rejects.toMatchObject({ status: 403 });
    expect(rules).not.toHaveBeenCalled();
    const unsubscribe = vi.fn(),
      subscribe = vi.fn(() => unsubscribe);
    Object.assign(api, { subscribe });
    expect(editor.subscribe?.(vi.fn())).toBe(unsubscribe);
  });
  it('solo copia decisiones después de una revisión válida y guarda la firma del rol', async () => {
    const api = new MockApi(),
      session = chooseRole('editor', null),
      guarded = roleApi(api, session, vi.fn());
    const detail = await api.topic('tema-mock-001');
    await expect(
      guarded.review(detail.case.caseId, {
        expectedVersion: 0,
        status: 'descartado',
        reviewer: session.labeler,
        comment: null,
      }),
    ).rejects.toBeTruthy();
    expect(readTeam().decisions).toEqual([]);
    const updated = await guarded.review(detail.case.caseId, {
      expectedVersion: 0,
      status: 'en_revision',
      reviewer: session.labeler,
      comment: 'Revisar fuentes originales',
    });
    expect(readTeam().decisions).toHaveLength(1);
    expect(readTeam().decisions[0]).toMatchObject({
      snapshotId: detail.snapshotId,
      status: 'en_revision',
      role: 'editor',
      caseVersion: updated.version,
    });
  });
  it.each(['producer', 'reviewer', 'juror'] as DemoRole[])(
    '%s no necesita contraseña para entrar',
    (role) => {
      expect(chooseRole(role, null)).toMatchObject({
        role,
        labeler: expect.any(String),
        sessionId: expect.any(String),
      });
    },
  );
});
