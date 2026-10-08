// localStorage solo como conveniencia por navegador (nombre del revisor); siempre con try/catch.
export function readLocal(key: string, fallback = ''): string {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
export function writeLocal(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* almacenamiento bloqueado */
  }
}
