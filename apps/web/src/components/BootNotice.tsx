import { useQueryClient } from '@tanstack/react-query';
import { fmtDateTime } from '../lib/format';
import { latestAgendaUpdate } from '../lib/queryCache';
import { useBoot } from './context';
import { ErrorBox, Notice } from './ui';

export function bootProgressText(progress: { attempt: number; elapsedMs: number } | null): string {
  return progress ? `Intento ${progress.attempt} · ${Math.floor(progress.elapsedMs / 1000)} s. ` : '';
}

/** Aviso mientras el backend despierta (Render Free puede tardar cerca de un minuto) o si el arranque falla. */
export function BootNotice() {
  const boot = useBoot();
  const queryClient = useQueryClient();
  if (boot.status === 'ready') return null;
  if (boot.status === 'error') {
    return (
      <div data-testid="app-boot-error">
        <ErrorBox error={new Error(boot.error ?? 'Error de arranque')} onRetry={boot.retry} />
      </div>
    );
  }
  const saved = latestAgendaUpdate(queryClient);
  return (
    <Notice
      tone="info"
      role="status"
      testId="boot-notice"
      title={saved ? 'Mostrando datos guardados de tu última visita' : 'Despertando el servidor…'}
    >
      <p aria-live="polite">
        {saved
          ? `Datos de ${fmtDateTime(new Date(saved).toISOString())}; se actualizarán cuando el servidor responda. `
          : 'La aplicación ya está lista; los datos aparecerán en cuanto el servidor responda. '}
        {bootProgressText(boot.progress)}El primer inicio puede tardar hasta 90 segundos.
      </p>
    </Notice>
  );
}
