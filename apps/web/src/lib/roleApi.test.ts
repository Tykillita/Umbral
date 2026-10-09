import { describe, expect, it, vi } from 'vitest';
import type { UmbralApi } from './api/client';
import type { CaseView, ReviewRequest, TopicDetail } from './api/types';
import { roleApi } from './roleApi';
import type { DemoSession } from './session';

vi.mock('./team', () => ({
  retrySharing: vi.fn(),
  sharedConfiguration: vi.fn(() => false),
  storeDecision: vi.fn(),
}));

describe('notificación de Slack después de revisar', () => {
  it('conserva la revisión aunque falle el aviso automático', async () => {
    const before = { caseId: 'case-x', topicId: 'topic-x', status: 'en_revision' } as CaseView;
    const after = { caseId: 'case-x', topicId: 'topic-x', status: 'aprobado_como_borrador', version: 4 } as CaseView;
    const detail = { snapshotId: '20261008-aabbccdd', summary: { title: 'Tema de ejemplo' }, case: before } as TopicDetail;
    const api = {
      kind: 'live',
      workspaceMode: 'browser',
      getCase: vi.fn().mockResolvedValue(before),
      topic: vi.fn().mockResolvedValue(detail),
      review: vi.fn().mockResolvedValue(after),
      notifySlackReview: vi.fn().mockRejectedValue(new Error('Slack temporalmente indisponible')),
    } as unknown as UmbralApi;
    const session: DemoSession = { role: 'reviewer', sessionId: 'session-test', labeler: 'Revisión de prueba' };
    const report = vi.fn();
    const wrapped = roleApi(api, session, report);
    const request: ReviewRequest = { expectedVersion: 3, status: 'aprobado_como_borrador', reviewer: 'Revisión de prueba' };

    const result = await wrapped.review('case-x', request);

    expect(api.review).toHaveBeenCalledOnce();
    expect(api.notifySlackReview).toHaveBeenCalledWith(expect.objectContaining({
      eventId: expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i),
      status: 'aprobado_como_borrador',
    }));
    expect(result).toBe(after);
    expect(report).toHaveBeenCalledWith(expect.stringContaining('La revisión quedó guardada'), false);
  });
});
