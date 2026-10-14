// Bloqueo del desplazamiento de la página compartido por todas las superficies (hoja de Select, Modal, asistente).
// Cada superficie guardaba y restauraba `overflow` por su cuenta: si se cerraban en otro orden quedaba un `hidden`
// permanente. Aquí hay un contador: el estado original se guarda al primer bloqueo y se restaura al soltar el último.
let locks = 0;
let saved: { body: string; root: string } | null = null;

/** Bloquea el scroll de la página y devuelve la función que libera este bloqueo (idempotente). */
export function lockScroll(): () => void {
  if (typeof document === 'undefined') return () => undefined;
  if (locks === 0) {
    saved = { body: document.body.style.overflow, root: document.documentElement.style.overflow };
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
  }
  locks += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    locks = Math.max(0, locks - 1);
    if (locks === 0 && saved) {
      document.body.style.overflow = saved.body;
      document.documentElement.style.overflow = saved.root;
      saved = null;
    }
  };
}

/** Solo para pruebas: número de bloqueos activos. */
export function activeScrollLocks(): number {
  return locks;
}
