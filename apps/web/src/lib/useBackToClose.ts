// En móvil el botón Atrás del sistema (Android) y el gesto de retroceso (iOS) deben cerrar la superficie abierta
// (asistente, hoja de selección, ventana) en lugar de cambiar de vista o salir de la aplicación.
// Al abrir se añade una entrada de historial con la misma URL (no dispara `hashchange`, así que el router no se entera);
// al retroceder se cierra SOLO la superficie de arriba de la pila. Si se cierra por otro medio, se retira su entrada.
import { useEffect, useRef } from 'react';

const KEY = 'umbralOverlay';

type Entry = { token: string; close: () => void };
const stack: Entry[] = [];
let ignorePops = 0;
let counter = 0;
let listening = false;

function onPop() {
  if (ignorePops > 0) {
    ignorePops -= 1;
    return;
  }
  const top = stack.pop();
  top?.close();
}

function ensureListener() {
  if (listening) return;
  listening = true;
  window.addEventListener('popstate', onPop);
}

export function useBackToClose(open: boolean, onClose: () => void): void {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open || typeof window === 'undefined') return;
    const token = `${Date.now()}-${(counter += 1)}`;
    try {
      window.history.pushState({ ...(window.history.state ?? {}), [KEY]: token }, '', window.location.href);
    } catch {
      return;
    }
    ensureListener();
    const entry: Entry = { token, close: () => closeRef.current() };
    stack.push(entry);
    return () => {
      const index = stack.indexOf(entry);
      if (index === -1) return; // ya se cerró con Atrás: la entrada de historial ya no existe
      stack.splice(index, 1);
      const state = window.history.state as Record<string, unknown> | null;
      // Solo se retrocede si la entrada actual sigue siendo la nuestra; si la ruta cambió, no se toca el historial.
      if (state && state[KEY] === token) {
        ignorePops += 1;
        window.history.back();
      }
    };
  }, [open]);
}

/** Solo para pruebas. */
export function overlayDepth(): number {
  return stack.length;
}
