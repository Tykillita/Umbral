import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { readTeam, retrySharing, sharedConfiguration, subscribeTeam } from '../lib/team';
import { Button, ErrorBox, Notice } from './ui';

export function useLocalTeam() {
  const client = useQueryClient();
  useEffect(
    () =>
      subscribeTeam(() => {
        void client.invalidateQueries({ queryKey: ['local-team'] });
      }),
    [client],
  );
  return useQuery({ queryKey: ['local-team'], queryFn: readTeam, staleTime: Infinity });
}
export function useSharedConfiguration() {
  try {
    return { configured: Boolean(sharedConfiguration()), error: null };
  } catch (error) {
    return { configured: false, error };
  }
}
export function TeamStatus() {
  const local = useLocalTeam(),
    client = useQueryClient();
  const { configured, error: configurationError } = useSharedConfiguration();
  const desktopShell = typeof window !== 'undefined' && Boolean(window.umbralDesktop?.windowControls);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null),
    [notice, setNotice] = useState('');
  const pending = local.data
    ? [...local.data.decisions.map((d) => d.eventId), ...local.data.labels.map((l) => l.id)].filter(
        (id) => !local.data!.published.includes(id),
      ).length
    : 0;
  return (
    <div className="space-y-2" data-testid="team-status">
      {(configured || !desktopShell) && (
        <Notice
          tone={!configured || pending ? 'warn' : 'info'}
          title={configured ? 'Mesa compartida y copia local' : 'Trabajo guardado en este navegador'}
          testId="team-storage-status"
        >
          {configured
            ? `${pending} entradas pendientes de compartir. Las confirmadas aparecen como compartidas; puedes reintentar las pendientes.`
            : 'La mesa compartida está sin configurar. Conserva tus decisiones y etiquetas localmente y descarga una copia para entregarlas.'}
          {configured && (
            <Button
              className="mt-2"
              icon={RefreshCw}
              busy={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                setNotice('');
                try {
                  const result = await retrySharing();
                  setNotice(`${result.count} entradas confirmadas en la mesa.`);
                  await Promise.all([
                    client.invalidateQueries({ queryKey: ['team-decisions'] }),
                    client.invalidateQueries({ queryKey: ['team-labels'] }),
                  ]);
                } catch (failure) {
                  setError(failure);
                } finally {
                  setBusy(false);
                }
              }}
              data-testid="team-retry"
            >
              Reintentar y actualizar mesa
            </Button>
          )}
          {notice && (
            <p className="mt-2" role="status">
              {notice}
            </p>
          )}
        </Notice>
      )}
      {Boolean(local.error || configurationError || error) && (
        <ErrorBox error={local.error || configurationError || error} />
      )}
    </div>
  );
}
