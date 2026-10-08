import { config } from './config';

const LOCAL_HOSTS = new Set(['localhost','127.0.0.1','[::1]','::1']);
export function validatePublicApiUrl(value: string, browserHost: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('La configuración de la API requiere una dirección completa válida.'); }
  const local = LOCAL_HOSTS.has(browserHost) && LOCAL_HOSTS.has(url.hostname);
  const render = /^[a-z0-9][a-z0-9-]*\.onrender\.com$/.test(url.hostname);
  if ((!local && (!render || url.protocol !== 'https:')) || (local && !['http:','https:'].includes(url.protocol)) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('La API pública requiere HTTPS en un servicio de Render, sin credenciales, rutas ni parámetros. El acceso HTTP a loopback sólo se admite al verificar en localhost.');
  }
  return url.origin;
}

export async function resolvePublicApiUrl(signal?: AbortSignal): Promise<string> {
  const host = window.location.hostname;
  if (config.apiUrl) return validatePublicApiUrl(config.apiUrl, host);
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 6000);
  const cancel = () => controller.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch('/public-config.json', { headers: { Accept: 'application/json' }, credentials: 'omit', cache: 'no-store', signal: controller.signal });
    if (response.status === 404 && LOCAL_HOSTS.has(host)) return '';
    if (!response.ok) throw new Error('Falta public-config.json o no se puede leer. Configura la dirección de la API de esta publicación y reintenta.');
    if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('public-config.json devolvió una página en lugar de configuración JSON.');
    const value = await response.json() as unknown;
    if (!value || typeof value !== 'object' || !('schemaVersion' in value) || value.schemaVersion !== 1 || !('apiUrl' in value) || typeof value.apiUrl !== 'string') throw new Error('public-config.json necesita schemaVersion=1 y apiUrl.');
    return validatePublicApiUrl(value.apiUrl, host);
  } catch (error) {
    if (signal?.aborted) throw new DOMException('Arranque cancelado', 'AbortError');
    if (error instanceof Error && error.name !== 'AbortError') throw error;
    throw new Error('No se pudo leer la configuración pública. Revisa la conexión y reintenta.');
  } finally { clearTimeout(timer); signal?.removeEventListener('abort', cancel); }
}
