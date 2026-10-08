import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Download, RotateCw, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import type { DesktopUpdateState } from '../lib/desktop';

const INITIAL: DesktopUpdateState = { status: 'idle' };

export default function DesktopUpdateNotice() {
  const bridge = typeof window !== 'undefined' ? window.umbralDesktop : undefined;
  const [state, setState] = useState<DesktopUpdateState>(INITIAL);
  const [dismissed, setDismissed] = useState(false);
  const lastStatus = useRef(INITIAL.status);

  useEffect(() => {
    if (!bridge?.getUpdateState) return;
    let active = true;
    let receivedEvent = false;
    const unsubscribe = bridge.onUpdateState((next) => {
      receivedEvent = true;
      const statusChanged = lastStatus.current !== next.status;
      lastStatus.current = next.status;
      setState(next);
      if (statusChanged) setDismissed(false);
    });
    void bridge.getUpdateState().then((next) => {
      if (active && !receivedEvent) { lastStatus.current = next.status; setState(next); }
    }).catch(() => {});
    return () => { active = false; unsubscribe(); };
  }, [bridge]);

  if (!bridge || dismissed || (state.status !== 'downloading' && state.status !== 'downloaded' && state.status !== 'error')) return null;
  const title = state.status === 'downloaded'
    ? `Umbral ${state.version} está lista para instalar`
    : state.status === 'error' ? 'No se pudo buscar una actualización' : 'Descargando una actualización de Umbral';
  const message = state.status === 'downloaded'
    ? 'Reinicia la aplicación cuando quieras para completar la instalación.'
    : state.status === 'error' ? 'Puedes seguir trabajando. Comprueba de nuevo cuando tengas conexión.'
      : 'La descarga continúa en segundo plano.';

  return createPortal(
    <section className="desktop-update-notice" aria-label="Actualización de Umbral" data-testid="desktop-update-notice">
      <div className="desktop-update-icon" aria-hidden="true">
        {state.status === 'error' ? <AlertTriangle size={20} /> : state.status === 'downloaded' ? <RotateCw size={20} /> : <Download size={20} />}
      </div>
      <div className="min-w-0 flex-1">
        <h2 className="desktop-update-title">{title}</h2>
        <p className="desktop-update-message" role="status" aria-live="polite" aria-atomic="true">{message}</p>
        {state.status === 'downloading' && <div className="desktop-update-track" role="progressbar" aria-label="Descarga de actualización" aria-valuemin={0} aria-valuemax={100} aria-valuenow={state.percent ?? 0}><span aria-hidden="true" style={{ width: `${state.percent ?? 0}%` }} /></div>}
        {state.status === 'downloading' && <span className="desktop-update-percent" aria-hidden="true">{state.percent ?? 0}%</span>}
        <div className="desktop-update-actions">
          {state.status === 'downloaded' && <button className="desktop-update-primary" type="button" onClick={() => void bridge.installUpdate()}>Reiniciar e instalar</button>}
          {state.status === 'error' && <button className="desktop-update-primary" type="button" onClick={() => { setDismissed(false); void bridge.checkForUpdates(); }}>Volver a comprobar</button>}
          <button className="desktop-update-close" type="button" aria-label="Cerrar aviso de actualización" onClick={() => setDismissed(true)}><X size={18} aria-hidden="true" /></button>
        </div>
      </div>
    </section>,
    document.body,
  );
}
