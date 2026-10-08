import { resolvePublicApiUrl } from '../publicConfig';
import { HttpApi, type BootProgress, type UmbralApi } from './client';
import { AuthError, getAuthToken } from '../auth';
import { config } from '../config';

export type ApiResolution = { api: UmbralApi; reason: string | null };
export async function resolveApi(onProgress?: (progress: BootProgress) => void, signal?: AbortSignal): Promise<ApiResolution> {
  const apiUrl = config.authMode === 'public' ? await resolvePublicApiUrl(signal) : config.apiUrl;
  const http = new HttpApi(apiUrl, config.authMode === 'public' ? async () => null : getAuthToken);
  // El modo público siempre usa datos reales; nunca activa un mock por error de conexión.
  if (config.authMode === 'public') {
    if (config.apiMode === 'mock') throw new Error('El modo público requiere PUBLIC_API_MODE=live.');
    await http.waitUntilReady(onProgress, signal);
    const { BrowserWorkspaceApi } = await import('./browserWorkspace');
    const api = new BrowserWorkspaceApi(http);
    try { await api.initialize(); } catch (error) { await api.close(); throw error; }
    return { api, reason: null };
  }
  if (config.apiMode === 'live') return { api: http, reason: null };
  if (config.apiMode === 'auto') {
    try { await http.health(); return { api: http, reason: null }; }
    catch (error) {
      if (error instanceof AuthError || !import.meta.env.DEV) throw error;
      const { MockApi } = await import('../mock/mockApi');
      return { api: new MockApi(), reason: 'La API no respondió (' + (error instanceof Error ? error.message : 'error') + ').' };
    }
  }
  const { MockApi } = await import('../mock/mockApi');
  return { api: new MockApi(), reason: 'Modo mock solicitado con PUBLIC_API_MODE=mock.' };
}
