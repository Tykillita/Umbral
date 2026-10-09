import { config, firebaseConfigured, firebaseRequested } from './config';

export type AuthState = { mode: 'public' | 'local' | 'firebase-anonymous'; uid: string | null; error: string | null };

let state: AuthState = { mode: config.authMode === 'public' ? 'public' : firebaseRequested ? 'firebase-anonymous' : 'local', uid: null, error: null };
let tokenGetter: (() => Promise<string | null>) | null = null;
let initPromise: Promise<AuthState> | null = null;
let connectorTokenGetter: (() => Promise<string>) | null = null;
let connectorInitPromise: Promise<() => Promise<string>> | null = null;

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
      await auth.authStateReady();
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

/**
 * La web pública no inicia una sesión para el trabajo editorial. Esta identidad anónima solo
 * acompaña las rutas de conectores, para que el servidor pueda aislar las credenciales OAuth.
 * Firebase conserva su propia sesión; Umbral nunca escribe tokens en localStorage.
 */
export async function getConnectorAuthToken(): Promise<string> {
  if (connectorTokenGetter) return connectorTokenGetter();
  if (!connectorInitPromise) {
    connectorInitPromise = (async () => {
      if (!firebaseConfigured) {
        throw new AuthError('Las conexiones requieren Firebase Auth anónima. La configuración aún no está disponible.');
      }
      const emulatorUrl = config.authEmulatorUrl
        ? validateAuthEmulatorUrl(config.authEmulatorUrl, window.location.hostname)
        : null;
      const [{ getApps, initializeApp }, { getAuth, signInAnonymously, connectAuthEmulator }] = await Promise.all([
        import('firebase/app'),
        import('firebase/auth'),
      ]);
      const app = getApps().find((candidate) => candidate.name === '[DEFAULT]') ?? initializeApp(config.firebase);
      const auth = getAuth(app);
      if (emulatorUrl && !auth.emulatorConfig) connectAuthEmulator(auth, emulatorUrl, { disableWarnings: true });
      await auth.authStateReady();
      if (!auth.currentUser) await signInAnonymously(auth);
      return async () => {
        const user = auth.currentUser;
        if (!user) throw new AuthError('La identidad anónima de Firebase terminó. Recarga Umbral para volver a conectarla.');
        return user.getIdToken();
      };
    })();
  }
  try {
    connectorTokenGetter = await connectorInitPromise;
    return await connectorTokenGetter();
  } catch (error) {
    connectorInitPromise = null;
    if (error instanceof AuthError) throw error;
    throw new AuthError(`No se pudo iniciar la identidad anónima para conectores: ${error instanceof Error ? error.message : 'Fallo de Firebase Auth'}`);
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
