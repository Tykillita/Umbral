// Configuración de build/entorno (solo valores PUBLIC_*, no secretos).
const env = import.meta.env;
const desktopFirebase = typeof window === 'undefined' ? undefined : window.umbralDesktop?.firebaseConfig;

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
  supabase: {
    url: String(env.PUBLIC_SUPABASE_URL ?? '').trim(),
    anonKey: String(env.PUBLIC_SUPABASE_ANON_KEY ?? '').trim(),
  },
  firebase: {
    apiKey: String(desktopFirebase?.apiKey ?? env.PUBLIC_FIREBASE_API_KEY ?? '').trim(),
    authDomain: String(desktopFirebase?.authDomain ?? env.PUBLIC_FIREBASE_AUTH_DOMAIN ?? '').trim(),
    projectId: String(desktopFirebase?.projectId ?? env.PUBLIC_FIREBASE_PROJECT_ID ?? '').trim(),
    appId: String(desktopFirebase?.appId ?? env.PUBLIC_FIREBASE_APP_ID ?? '').trim(),
  },
};

export const firebaseConfigured = Boolean(
  config.firebase.apiKey && config.firebase.authDomain && config.firebase.projectId && config.firebase.appId,
);

export const firebaseRequested = config.authMode === 'firebase' ||
  (config.authMode === 'auto' && Object.values(config.firebase).some(Boolean));
