/** Per-browser preferences (language, theme). Storage may be blocked, so every access is guarded. */

export const LANGUAGES = ["es", "en"] as const;
export type Language = (typeof LANGUAGES)[number];
export const THEMES = ["light", "dark", "system"] as const;
export type Theme = (typeof THEMES)[number];

export const LANGUAGE_STORAGE_KEY = "conector.language";
export const THEME_STORAGE_KEY = "conector.theme";
export const DEFAULT_LANGUAGE: Language = "es";
export const DEFAULT_THEME: Theme = "system";

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Blocked or full storage: the choice still applies to this page view.
  }
}

export function readLanguage(): Language {
  const stored = readStored(LANGUAGE_STORAGE_KEY);
  return LANGUAGES.find((language) => language === stored) ?? DEFAULT_LANGUAGE;
}

/** Remembers the language and updates `<html lang>`; switching i18next is the caller's job. */
export function writeLanguage(language: Language): void {
  writeStored(LANGUAGE_STORAGE_KEY, language);
  document.documentElement.lang = language;
}

export function readTheme(): Theme {
  const stored = readStored(THEME_STORAGE_KEY);
  return THEMES.find((theme) => theme === stored) ?? DEFAULT_THEME;
}

function systemPrefersDark(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

/** Toggles the `.dark` class the design tokens key off; `system` follows the OS preference. */
export function applyTheme(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", dark);
}

export function writeTheme(theme: Theme): void {
  writeStored(THEME_STORAGE_KEY, theme);
  applyTheme(theme);
}

/** Re-applies the stored theme when the OS preference changes. Returns the unsubscribe. */
export function watchSystemTheme(): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if (readTheme() === "system") applyTheme("system");
  };
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
