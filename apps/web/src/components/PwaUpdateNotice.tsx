import { useEffect, useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import { applyUpdate, registerServiceWorker, subscribeUpdateAvailable } from '../lib/pwa';

/** Registra el service worker y avisa cuando hay una versión nueva instalada en segundo plano. */
export default function PwaUpdateNotice() {
  const [available, setAvailable] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    registerServiceWorker();
    return subscribeUpdateAvailable(setAvailable);
  }, []);

  if (!available || dismissed || typeof document === 'undefined') return null;

  return createPortal(
    <section className="pwa-update" aria-label="Actualización de Umbral" data-testid="pwa-update-notice">
      <div className="pwa-update-icon" aria-hidden="true"><RefreshCw size={20} /></div>
      <div className="min-w-0 flex-1">
        <h2 className="pwa-update-title">Hay una versión nueva de Umbral</h2>
        <p className="pwa-update-message" role="status" aria-live="polite">
          {applying ? 'Actualizando…' : 'Se descargó en segundo plano. Actualiza cuando termines lo que estás haciendo.'}
        </p>
        <div className="pwa-update-actions">
          <button
            type="button"
            className="pwa-update-primary"
            disabled={applying}
            data-testid="pwa-update-apply"
            onClick={() => { setApplying(true); applyUpdate(); }}
          >
            Actualizar ahora
          </button>
          <button type="button" className="pwa-update-close" aria-label="Recordármelo más tarde" onClick={() => setDismissed(true)}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      </div>
    </section>,
    document.body,
  );
}
