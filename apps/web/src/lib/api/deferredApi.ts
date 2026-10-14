import type { UmbralApi } from './client';

/** Métodos obligatorios del contrato: antes de que el arranque termine, se encolan y esperan a la API real. */
const REQUIRED: (keyof UmbralApi)[] = [
  'health', 'rules', 'updateRules', 'connections', 'startConnection', 'selectConnection', 'connectionModels',
  'selectConnectionModel', 'disconnect', 'claudeConnection', 'startClaudeLogin', 'claudeLogout', 'snapshot',
  'alerts', 'today', 'refreshNews', 'topics', 'topic', 'query', 'compose', 'createDraft', 'saveDraft', 'review', 'setImpact', 'getCase', 'exportCase',
];

export interface DeferredApi {
  /** Se comporta como `UmbralApi`; cada llamada espera a que `resolve` entregue la API real. */
  api: UmbralApi;
  resolve(api: UmbralApi): void;
  reject(error: unknown): void;
}

/**
 * Permite pintar la aplicación mientras el backend despierta. Las consultas quedan pendientes (con los datos
 * guardados a la vista) y se ejecutan cuando llega la API real; si el arranque falla, fallan con ese error.
 * Los métodos opcionales (conectores, copia del espacio) no existen hasta entonces: la interfaz ya los trata
 * como «no disponible» y se reevalúa cuando el contexto pasa a la API real.
 */
export function createDeferredApi(workspaceMode?: 'browser'): DeferredApi {
  let resolveReady!: (api: UmbralApi) => void;
  let rejectReady!: (error: unknown) => void;
  const ready = new Promise<UmbralApi>((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
  ready.catch(() => undefined); // Los errores llegan a quien llame; esto evita un rechazo sin atender.
  const lazy = new Map<PropertyKey, (...args: unknown[]) => Promise<unknown>>();
  const target = { kind: 'live' as const, workspaceMode };
  const api = new Proxy(target, {
    get(base, key) {
      if (key === 'kind' || key === 'workspaceMode') return base[key];
      if (!REQUIRED.includes(key as keyof UmbralApi)) return undefined;
      let call = lazy.get(key);
      if (!call) {
        call = async (...args: unknown[]) => {
          const real = await ready;
          return (real[key as keyof UmbralApi] as (...values: unknown[]) => Promise<unknown>).apply(real, args);
        };
        lazy.set(key, call);
      }
      return call;
    },
  }) as unknown as UmbralApi;
  return { api, resolve: resolveReady, reject: rejectReady };
}
