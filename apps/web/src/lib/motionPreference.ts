export type MotionPreference = 'system' | 'reduced' | 'full';

export const MOTION_PREFERENCE_STORAGE_KEY = 'umbral.motion-preference.v1';

export function isMotionPreference(value: unknown): value is MotionPreference {
  return value === 'system' || value === 'reduced' || value === 'full';
}

export function getMotionPreference(): MotionPreference {
  const rootPreference = typeof document === 'undefined' ? undefined : document.documentElement.dataset.motionPreference;
  if (isMotionPreference(rootPreference)) return rootPreference;

  const desktopPreference = typeof window === 'undefined' ? undefined : window.umbralDesktop?.motionPreference;
  if (isMotionPreference(desktopPreference)) return desktopPreference;

  try {
    const stored = typeof window === 'undefined' ? null : window.localStorage.getItem(MOTION_PREFERENCE_STORAGE_KEY);
    if (isMotionPreference(stored)) return stored;
  } catch {
    // El ajuste efectivo puede seguir funcionando durante esta sesión si el almacenamiento está bloqueado.
  }
  return 'system';
}

export function applyMotionPreference(preference: MotionPreference): void {
  if (typeof document !== 'undefined') document.documentElement.dataset.motionPreference = preference;
}

export async function persistMotionPreference(preference: MotionPreference): Promise<void> {
  if (typeof window === 'undefined') return;
  const desktop = window.umbralDesktop;
  if (desktop?.setMotionPreference) {
    await desktop.setMotionPreference(preference);
    return;
  }
  window.localStorage.setItem(MOTION_PREFERENCE_STORAGE_KEY, preference);
}
