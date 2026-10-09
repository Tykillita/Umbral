import { writeLocal } from './storage';

export type ThemePreference = 'original' | 'tvn';

export const THEME_PREFERENCE_STORAGE_KEY = 'umbral.theme.v1';

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'original' || value === 'tvn';
}

export function getThemePreference(): ThemePreference {
  const rootTheme = typeof document === 'undefined' ? undefined : document.documentElement.dataset.theme;
  if (typeof window === 'undefined') return isThemePreference(rootTheme) ? rootTheme : 'original';

  try {
    const stored = window.localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY);
    if (stored === null) return isThemePreference(rootTheme) ? rootTheme : 'original';
    return isThemePreference(stored) ? stored : 'original';
  } catch {
    return isThemePreference(rootTheme) ? rootTheme : 'original';
  }
}

export function applyThemePreference(theme: ThemePreference): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = theme;
  const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (themeColor) themeColor.content = theme === 'tvn' ? '#F3F8FC' : '#FFF7DF';
}

export function persistThemePreference(theme: ThemePreference): void {
  writeLocal(THEME_PREFERENCE_STORAGE_KEY, theme);
  applyThemePreference(theme);
}
