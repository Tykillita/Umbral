import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { fetchDecisions, mergeById, type TeamDecision } from '../../lib/team';
import { useHealth } from '../../lib/hooks';
import { fmtDateTime } from '../../lib/format';
import type { ReviewStatus } from '../../lib/api/types';
import { useApp } from '../context';
import { TeamStatus, useLocalTeam, useSharedConfiguration } from '../TeamStatus';
import { Button, Card, ErrorBox, Loading, ReviewPill, SectionTitle } from '../ui';

const COLUMNS: ReviewStatus[] = ['en_revision', 'requiere_evidencia', 'aprobado_como_borrador', 'descartado'];
export function downloadJson(value: unknown, name: string): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function Mesa() {
  const { go } = useApp(),
    health = useHealth(),
    local = useLocalTeam();
  const { configured } = useSharedConfiguration();
  const remote = useQuery({
    queryKey: ['team-decisions'],
    queryFn: fetchDecisions,
    enabled: configured,
    refetchInterval: 20000,
    retry: false,
  });
  const history = useMemo(
    () =>
      mergeById(local.data?.decisions ?? [], remote.data ?? [], (d) => d.eventId).sort(
        (a, b) => b.createdAt.localeCompare(a.createdAt) || b.eventId.localeCompare(a.eventId),
      ),
    [local.data, remote.data],
  );
  const latest = useMemo(() => {
    const map = new Map<string, TeamDecision>();
    for (const event of history) {
      const key = `${event.snapshotId}:${event.caseId}`;
      const previous = map.get(key);
      if (!previous) map.set(key, event);
    }
    return [...map.values()];
  }, [history]);
  const shared = (decision: TeamDecision) =>
    remote.data?.some((d) => d.eventId === decision.eventId) ||
    local.data?.published.includes(decision.eventId);
  const caseLink = (decision: TeamDecision) =>
    decision.snapshotId === health.data?.snapshotId ? (
      <button
        className="comic-link text-left font-semibold underline underline-offset-2"
        type="button"
        onClick={() => go({ view: 'ficha', topicId: decision.topicId })}
      >
        {decision.title}
      </button>
    ) : (
      <strong className="block">{decision.title}</strong>
    );
  return (
    <div className="space-y-4" data-testid="mesa-view">
      <Card>
        <SectionTitle
          heading
          kicker="Control humano · equipo"
          aside={
            <Button
              icon={Download}
              disabled={!history.length}
              onClick={() => downloadJson({ version: 1, decisions: history }, 'mesa-umbral.json')}
            >
              Descargar historial
            </Button>
          }
        >
          Mesa compartida
        </SectionTitle>
        <p className="text-sm text-ink-2">
          {history.length} decisiones en {latest.length} casos. Aprobar como borrador no publica. El historial
          conserva cada decisión y se actualiza cada 20 segundos cuando la mesa está configurada.
        </p>
      </Card>
      <TeamStatus />
      {remote.error && <ErrorBox error={remote.error} onRetry={() => remote.refetch()} />}
      {local.isLoading && <Loading label="Cargando copia local de la mesa…" />}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {COLUMNS.map((status) => {
          const cases = latest.filter((event) => event.status === status);
          return (
            <Card key={status} data-testid={`mesa-column-${status}`}>
              <div className="mb-3 flex justify-between gap-2">
                <ReviewPill status={status} />
                <span className="text-sm font-semibold">{cases.length}</span>
              </div>
              {cases.length ? (
                <ul className="space-y-2">
                  {cases.map((decision) => (
                    <li
                      key={decision.eventId}
                      className="rounded border border-rule-strong bg-paper p-3 text-sm"
                    >
                      {caseLink(decision)}
                      <p className="mt-1 text-xs text-ink-3">
                        {decision.labeler} · {fmtDateTime(decision.createdAt)}
                      </p>
                      <p className="mt-1 text-xs text-ink-3">
                        {shared(decision) ? 'Compartido' : 'Solo local · pendiente'} · corte{' '}
                        {decision.snapshotId}
                        {decision.snapshotId !== health.data?.snapshotId ? ' (corte anterior)' : ''}
                      </p>
                      {decision.comment && <p className="mt-2">{decision.comment}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-ink-3">Sin casos.</p>
              )}
            </Card>
          );
        })}
      </div>
      <Card>
        <SectionTitle kicker="Trazabilidad">Historial del equipo</SectionTitle>
        {history.length ? (
          <ol className="divide-y divide-rule">
            {history.map((decision) => (
              <li key={decision.eventId} className="flex flex-wrap items-start gap-x-3 gap-y-2 py-3 text-sm">
                <span className="text-xs text-ink-3">{fmtDateTime(decision.createdAt)}</span>
                <ReviewPill status={decision.status} />
                <span className="min-w-0 flex-1">
                  <strong>{decision.labeler}</strong> · {caseLink(decision)}
                  {decision.comment && <span className="block">{decision.comment}</span>}
                  <span className="block text-xs text-ink-3">
                    Corte {decision.snapshotId} · versión local {decision.caseVersion} ·{' '}
                    {shared(decision) ? 'compartido' : 'solo local'}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-ink-3">Abre una ficha para registrar la primera decisión del equipo.</p>
        )}
        <p className="mt-3 text-xs text-ink-3">
          Las decisiones se agregan al historial; no se pueden editar ni borrar. Cada navegador mantiene su
          propio borrador y versión. La columna muestra la última decisión por corte y caso según su fecha
          registrada.
        </p>
      </Card>
    </div>
  );
}
