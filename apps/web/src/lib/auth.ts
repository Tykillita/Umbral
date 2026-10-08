import { config, firebaseConfigured, firebaseRequested } from './config';

export type AuthState = { mode: 'public' | 'local' | 'firebase-anonymous'; uid: string | null; error: string | null };

let state: AuthState = { mode: config.authMode === 'public' ? 'public' : firebaseRequested ? 'firebase-anonymous' : 'local', uid: null, error: null };
let tokenGetter: (() => Promise<string | null>) | null = null;
let initPromise: Promise<AuthState> | null = null;

/**
 * local omite Firebase incluso si hay configuración guardada. firebase requiere configuración completa.
 * auto selecciona Firebase si se ha configurado algún campo; un fallo nunca cambia a usuario local.
 * El SDK se carga bajo demanda para no pesar ni necesitar red en modo local.
 */
export function initAuth(): Promise<AuthState> {
  if (import.meta.env.PUBLIC_AUTH_MODE === 'public') return Promise.resolve({ mode: 'public', uid: null, error: null });
  if (initPromise) return initPromise;
  initPromise = (async () => {
    try {
      if (!['public', 'local', 'firebase', 'auto'].includes(config.authMode)) {
        throw new Error('PUBLIC_AUTH_MODE debe ser public, local, firebase o auto.');
      }
      if (!firebaseRequested) return state;
      if (!firebaseConfigured) {
        throw new Error('Firebase requiere las cuatro variables PUBLIC_FIREBASE_*. Revisa la configuración de autenticación.');
      }
      const emulatorUrl = config.authEmulatorUrl
        ? validateAuthEmulatorUrl(config.authEmulatorUrl, window.location.hostname)
        : null;
      const [{ initializeApp }, { getAuth, signInAnonymously, connectAuthEmulator }] = await Promise.all([
        import('firebase/app'),
        import('firebase/auth'),
      ]);
      const app = initializeApp(config.firebase);
      const auth = getAuth(app);
      if (emulatorUrl) connectAuthEmulator(auth, emulatorUrl, { disableWarnings: true });
      const cred = auth.currentUser ? { user: auth.currentUser } : await signInAnonymously(auth);
      tokenGetter = async () => {
        if (!auth.currentUser) throw new AuthError('La sesión de Firebase terminó. Recarga para iniciar otra sesión.');
        return auth.currentUser.getIdToken();
      };
      state = { mode: 'firebase-anonymous', uid: cred.user.uid, error: null };
    } catch (e) {
      state = { ...state, error: `No se pudo iniciar la sesión: ${e instanceof Error ? e.message : 'Fallo de Firebase Auth'}` };
    }
    return state;
  })();
  return initPromise;
}

export async function getAuthToken(): Promise<string | null> {
  const auth = await initAuth();
  if (auth.error) throw new AuthError(auth.error);
  try {
    return tokenGetter ? await tokenGetter() : null;
  } catch (e) {
    throw new AuthError(e instanceof Error ? e.message : 'No se pudo renovar la sesión de Firebase.');
  }
}

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthError';
  }
}

/** Una build de verificación nunca puede enviar sesiones alojadas al emulador. */
export function validateAuthEmulatorUrl(value: string, browserHost: string): string {
  const localHosts = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
  const url = new URL(value);
  if (!localHosts.has(browserHost) || !localHosts.has(url.hostname) ||
      !['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new AuthError('El emulador de Firebase solo se admite en una aplicación y URL de localhost.');
  }
  return url.origin;
}

export function authState(): AuthState {
  return state;
}
