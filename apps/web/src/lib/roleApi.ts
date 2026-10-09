import { ApiError, type UmbralApi } from './api/client';
import type { ReviewRequest } from './api/types';
import { canPerform, type DemoSession, type RoleAction } from './session';
import { retrySharing, sharedConfiguration, storeDecision } from './team';

const GUARDED: Partial<Record<keyof UmbralApi, RoleAction>> = {
  updateRules: 'rules',
  setImpact: 'impact',
  createDraft: 'createDraft',
  saveDraft: 'editDraft',
  review: 'review',
  importWorkspace: 'importWorkspace',
};
/** Permisos de demostración en llamadas directas y controles. No representa autenticación del servidor. */
export function roleApi(
  api: UmbralApi,
  session: DemoSession | null,
  report: (message: string, shared: boolean) => void,
): UmbralApi {
  return new Proxy(api, {
    get(target, key) {
      const value = Reflect.get(target, key);
      if (typeof value !== 'function') return value;
      if (!GUARDED[key as keyof UmbralApi]) return value.bind(target);
      return async (...args: unknown[]) => {
        const action = GUARDED[key as keyof UmbralApi];
        if (action && (!session || !canPerform(session.role, action)))
          throw new ApiError(403, {
            code: 'rol_demo',
            message: 'Esta acción corresponde a otro rol. Cambia tu rol para continuar.',
          });
        const detail =
          key === 'review'
            ? await target.getCase(args[0] as string).then((entry) => target.topic(entry.topicId))
            : null;
        const result = await value.apply(target, args);
        if (key === 'review' && session) {
          if (!detail) {
            report('La decisión se guardó, pero no se pudo recuperar la ficha para compartirla con el equipo.', false);
            return result;
          }
          const decision = result as Awaited<ReturnType<UmbralApi['review']>>;
          const body = args[1] as ReviewRequest;
          // La clave UUID se guarda con la decisión y se reutiliza al reintentar compartirla.
          const eventId = crypto.randomUUID();
          let message = 'Decisión guardada en este navegador. La mesa compartida está sin configurar.';
          let shared = false;
          try {
            await storeDecision({
              eventId,
              snapshotId: detail.snapshotId,
              topicId: decision.topicId,
              caseId: decision.caseId,
              caseVersion: decision.version,
              status: decision.status,
              ...session,
              title: detail.summary.title,
              comment: body.comment ?? '',
              createdAt: decision.updatedAt ?? new Date().toISOString(),
            });
            if (sharedConfiguration()) {
              await retrySharing();
              message = 'Decisión guardada y compartida con el equipo.';
              shared = true;
            }
          } catch (error) {
            message = `La revisión se guardó. ${error instanceof Error ? error.message : 'No se pudo compartir la copia; reintenta desde Mesa.'}`;
          }
          if (target.workspaceMode === 'browser' && detail.case.status !== decision.status && target.notifySlackReview) {
            try {
              const notification = await target.notifySlackReview({
                eventId,
                caseId: decision.caseId,
                caseVersion: decision.version,
                title: detail.summary.title,
                status: decision.status,
                snapshotId: detail.snapshotId,
              });
              if (notification.sent) message += ' Aviso enviado a Slack.';
            } catch (error) {
              message += ` La revisión quedó guardada, pero falló el aviso de Slack: ${error instanceof Error ? error.message : 'inténtalo de nuevo más tarde.'}`;
            }
          }
          report(message, shared);
        }
        return result;
      };
    },
  });
}
