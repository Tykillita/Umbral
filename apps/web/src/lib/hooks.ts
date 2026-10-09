import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useApp } from '../components/context';
import type { DraftEditRequest, DraftProviderChoice, ImpactRequest, ReviewRequest, RulesRequest, TopicFilters } from './api/types';
import { desktopConnectorEnabled } from './desktop';

export const qk = {
  health: ['health'] as const,
  rules: ['rules'] as const,
  snapshot: ['snapshot'] as const,
  topics: (f: TopicFilters) => ['topics', f] as const,
  alerts: ['alerts'] as const,
  topic: (id: string) => ['topic', id] as const,
};

export function useHealth() {
  const { api } = useApp();
  return useQuery({ queryKey: [...qk.health, api.kind], queryFn: () => api.health(), refetchInterval: 60_000, retry: 1 });
}

export function useRules() {
  const { api } = useApp();
  return useQuery({ queryKey: [...qk.rules, api.kind], queryFn: () => api.rules(), staleTime: 10 * 60_000 });
}

export function useUpdateRules() {
  const { api } = useApp();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RulesRequest) => api.updateRules(body),
    onSuccess: async (rules) => {
      qc.setQueryData([...qk.rules, api.kind], rules);
      await Promise.all([qc.invalidateQueries({ queryKey: ['topics'] }), qc.invalidateQueries({ queryKey: ['topic'] })]);
    },
  });
}

export function useSnapshot() {
  const { api } = useApp();
  return useQuery({ queryKey: [...qk.snapshot, api.kind], queryFn: () => api.snapshot() });
}

export function useTopics(filters: TopicFilters) {
  const { api } = useApp();
  return useQuery({ queryKey: [...qk.topics(filters), api.kind], queryFn: () => api.topics(filters), placeholderData: (prev) => prev });
}

export function useAlerts() {
  const { api } = useApp();
  return useQuery({ queryKey: [...qk.alerts, api.kind], queryFn: () => api.alerts(), refetchInterval: 60_000, refetchIntervalInBackground: false, staleTime: 30_000, retry: 1 });
}

export function useTopic(topicId: string | null) {
  const { api } = useApp();
  return useQuery({
    queryKey: [...qk.topic(topicId ?? ''), api.kind],
    queryFn: () => api.topic(topicId as string),
    enabled: Boolean(topicId),
  });
}

/** Tras cualquier cambio de caso se refresca la ficha y la agenda (estado de revisión visible en tarjetas). */
function useInvalidateCase(topicId: string) {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ['topic', topicId] }), qc.invalidateQueries({ queryKey: ['topics'] })]);
}

export function useCreateDraft(topicId: string) {
  const { api } = useApp();
  const inv = useInvalidateCase(topicId);
  return useMutation({ mutationFn: (provider: DraftProviderChoice) => api.createDraft(topicId, provider), onSuccess: inv });
}

export function useSaveDraft(topicId: string, caseId: string) {
  const { api } = useApp();
  const inv = useInvalidateCase(topicId);
  return useMutation({ mutationFn: (body: DraftEditRequest) => api.saveDraft(caseId, body), onSuccess: inv });
}

export function useReview(topicId: string, caseId: string) {
  const { api, authMode, showToast } = useApp();
  const inv = useInvalidateCase(topicId);
  return useMutation({
    mutationFn: (body: ReviewRequest) => api.review(caseId, body),
    onSuccess: (updated) => {
      void inv().catch(() => undefined);
      const canNotify = authMode === 'public' || desktopConnectorEnabled();
      const lastEvent = updated.history[updated.history.length - 1];
      if (!canNotify || !api.connectorOverview || !api.notifySlackReview || !lastEvent || lastEvent.fromStatus === updated.status) return;
      void (async () => {
        let notificationWasEnabled = false;
        try {
          const overview = await api.connectorOverview!();
          const preferences = overview.slackNotifications;
          notificationWasEnabled = preferences.enabled && Boolean(overview.providers.slack.connected && overview.providers.slack.channelId) && preferences.statuses.includes(updated.status);
          if (!notificationWasEnabled) return;
          const detail = await api.topic(topicId);
          await api.notifySlackReview!({
            eventId: `review:${caseId}:${updated.version}:${updated.status}`,
            caseId,
            caseVersion: updated.version,
            title: detail.summary.title,
            status: updated.status,
            snapshotId: updated.snapshotId,
          });
        } catch {
          if (notificationWasEnabled) showToast({
            tone: 'error',
            title: 'Revisión guardada; aviso de Slack pendiente',
            description: 'El cambio quedó guardado, pero no se pudo enviar el aviso automático.',
          });
        }
      })();
    },
  });
}

export function useSetImpact(topicId: string) {
  const { api } = useApp();
  const inv = useInvalidateCase(topicId);
  return useMutation({ mutationFn: (body: ImpactRequest) => api.setImpact(topicId, body), onSuccess: inv });
}
