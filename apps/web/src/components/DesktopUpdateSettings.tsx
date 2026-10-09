import { useEffect, useState } from 'react';
import type { DesktopUpdateState } from '../lib/desktop';
import { Button } from './ui';
import { Checkbox } from './ui/controls';

const INITIAL: DesktopUpdateState = { status: 'idle' };

function statusText(state: DesktopUpdateState): string {
  switch (state.status) {
    case 'checking': return 'Buscando actualizaciones…';
    case 'available': return `Umbral ${state.version ?? ''} está disponible. Pulsa «Actualizar ahora».`.replace('  ', ' ');
    case 'downloading': return `Descargando ${state.version ? `Umbral ${state.version}` : 'la actualización'}… ${state.percent ?? 0}%`;
    case 'downloaded': return `Umbral ${state.version ?? ''} está lista para instalar.`.replace('  ', ' ');
    case 'error': return 'No se pudo comprobar. Puedes seguir trabajando e intentarlo de nuevo.';
    default: return 'No hay actualizaciones pendientes.';
  }
}

export function DesktopUpdateSettings() {
  const bridge = typeof window !== 'undefined' ? window.umbralDesktop : undefined;
  const [state, setState] = useState<DesktopUpdateState>(INITIAL);
  const [enabled, setEnabled] = useState<boolean>(bridge?.autoUpdateEnabled ?? true);
  const [failure, setFailure] = useState('');

  useEffect(() => {
    if (!bridge?.getUpdateState) return;
    let live = true;
    const subscribe = (next: DesktopUpdateState) => {
      if (!live) return;
      if (typeof next.autoUpdateEnabled === 'boolean') setEnabled(next.autoUpdateEnabled);
      setState(next);
    };
    const unsubscribe = bridge.onUpdateState(subscribe);
    void bridge.getUpdateState().then(subscribe).catch(() => {});
    return () => { live = false; unsubscribe(); };
  }, [bridge]);

  if (!bridge?.getUpdateState) return null;

  const busy = state.status === 'checking' || state.status === 'downloading';
  const canUpdateNow = state.status === 'available' || state.status === 'downloaded';

  const toggle = (value: boolean) => {
    setEnabled(value);
    setFailure('');
    void bridge.setAutoUpdateEnabled?.(value).catch(() => setFailure('No se pudo guardar la preferencia.'));
  };
  const check = () => { setFailure(''); void bridge.checkForUpdates().catch(() => setFailure('No se pudo buscar actualizaciones.')); };
  const updateNow = () => { setFailure(''); void bridge.updateNow?.().catch(() => setFailure('No se pudo iniciar la actualización.')); };

  return <div className="space-y-3" data-testid="desktop-update-settings">
    <Checkbox testId="desktop-auto-update" checked={enabled} disabled={!bridge.setAutoUpdateEnabled} onChange={toggle}>
      Buscar e instalar actualizaciones automáticamente
    </Checkbox>
    <p className="text-xs text-ink-3">Con esta opción activa, Umbral descarga e instala sola las versiones nuevas. Si la desactivas, seguirá avisando cuando haya una actualización, pero no descargará nada hasta que pulses «Actualizar ahora».</p>
    <div className="flex flex-wrap gap-2">
      <Button data-testid="desktop-check-updates" disabled={busy} busy={state.status === 'checking'} onClick={check}>Buscar actualizaciones</Button>
      <Button data-testid="desktop-update-now" variant="primary" disabled={busy || !canUpdateNow} busy={state.status === 'downloading'} onClick={updateNow}>Actualizar ahora</Button>
    </div>
    <p className="text-sm text-ink-2" role="status" aria-live="polite" data-testid="desktop-update-status">{statusText(state)}</p>
    {failure && <p className="text-sm text-bad" role="alert" data-testid="desktop-update-error">{failure}</p>}
  </div>;
}
