// Registro del service worker (public/sw.js) y estado de «hay una versión nueva».
// - Solo en producción y en contexto seguro (https o localhost).
// - No se registra en la app de escritorio: ahí el mismo build lo sirve el propio programa y no hace falta caché del navegador.
// - Una versión nueva se instala en segundo plano y espera: la activa la persona con «Actualizar» (SKIP_WAITING) y la
//   página se recarga una sola vez cuando el nuevo worker toma el control.

type Listener = (waiting: boolean) => void;

let waitingWorker: ServiceWorker | null = null;
const listeners = new Set<Listener>();
let reloading = false;
let started = false;

function setWaiting(worker: ServiceWorker | null) {
  waitingWorker = worker;
  for (const listener of listeners) listener(worker !== null);
}

export function subscribeUpdateAvailable(listener: Listener): () => void {
  listeners.add(listener);
  listener(waitingWorker !== null);
  return () => { listeners.delete(listener); };
}

/** Activa la versión nueva; la página se recarga cuando el worker nuevo toma el control. */
export function applyUpdate(): void {
  waitingWorker?.postMessage({ type: 'SKIP_WAITING' });
}

export function shouldRegisterServiceWorker(): boolean {
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return false;
  if (!import.meta.env.PROD || !window.isSecureContext) return false;
  const desktop = (window as unknown as { umbralDesktop?: unknown }).umbralDesktop;
  return !desktop;
}

export function registerServiceWorker(): void {
  if (started || !shouldRegisterServiceWorker()) return;
  started = true;
  const hadController = !!navigator.serviceWorker.controller;

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // La primera instalación también cambia de controlador; solo se recarga si ya había una versión anterior en uso.
    if (!hadController || reloading) return;
    reloading = true;
    window.location.reload();
  });

  void navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' }).then((registration) => {
    const track = (worker: ServiceWorker | null) => {
      if (!worker) return;
      const onState = () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) setWaiting(worker);
        // Un worker que ya se activó (o quedó obsoleto) deja de estar «esperando»: sin esto el aviso se quedaba fijo en WebKit.
        else if (worker === waitingWorker && worker.state !== 'installed') setWaiting(null);
      };
      worker.addEventListener('statechange', onState);
      onState();
    };
    if (registration.waiting && navigator.serviceWorker.controller) setWaiting(registration.waiting);
    track(registration.installing);
    registration.addEventListener('updatefound', () => track(registration.installing));

    // Comprobar si hay versión nueva al volver a la app (típico en PWA instalada, que casi nunca se recarga) y cada hora.
    const check = () => { void registration.update().catch(() => undefined); };
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') check(); });
    window.setInterval(check, 60 * 60 * 1000);
  }).catch(() => {
    // Sin service worker la app funciona igual (solo en línea).
  });
}
