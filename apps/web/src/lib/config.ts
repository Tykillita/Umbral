// Configuración de build/entorno (solo valores PUBLIC_*, no secretos).
const env = import.meta.env;

export type ApiMode = 'live' | 'mock' | 'auto';
export type AuthMode = 'public' | 'local' | 'firebase' | 'auto';

function resolveMode(): ApiMode {
  const raw = String(env.PUBLIC_API_MODE ?? '').toLowerCase();
  if (raw === 'live' || raw === 'mock' || raw === 'auto') return raw;
  return env.DEV ? 'auto' : 'live';
}

export const config = {
  apiUrl: String(env.PUBLIC_API_URL ?? '').trim(),
  apiMode: resolveMode(),
  authMode: String(env.PUBLIC_AUTH_MODE ?? 'auto').trim().toLowerCase() as AuthMode,
  authEmulatorUrl: String(env.PUBLIC_FIREBASE_AUTH_EMULATOR_URL ?? '').trim(),
  firebase: {
    apiKey: String(env.PUBLIC_FIREBASE_API_KEY ?? '').trim(),
    authDomain: String(env.PUBLIC_FIREBASE_AUTH_DOMAIN ?? '').trim(),
    projectId: String(env.PUBLIC_FIREBASE_PROJECT_ID ?? '').trim(),
    appId: String(env.PUBLIC_FIREBASE_APP_ID ?? '').trim(),
  },
};

export const firebaseConfigured = Boolean(
  config.firebase.apiKey && config.firebase.authDomain && config.firebase.projectId && config.firebase.appId,
);

export const firebaseRequested = config.authMode === 'firebase' ||
  (config.authMode === 'auto' && Object.values(config.firebase).some(Boolean));
