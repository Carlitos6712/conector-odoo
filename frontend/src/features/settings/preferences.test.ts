import {
  applyTheme,
  LANGUAGE_STORAGE_KEY,
  readLanguage,
  readTheme,
  THEME_STORAGE_KEY,
  watchSystemTheme,
  writeLanguage,
  writeTheme,
} from "@/features/settings/preferences";

function stubMatchMedia(matches: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  };
  vi.stubGlobal("matchMedia", () => query);
  return {
    flip(next: boolean) {
      query.matches = next;
      listeners.forEach((fn) => fn());
    },
    listeners,
  };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  document.documentElement.lang = "";
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("language preference", () => {
  it("defaults to Spanish and ignores unknown stored values", () => {
    expect(readLanguage()).toBe("es");
    localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
    expect(readLanguage()).toBe("es");
  });

  it("persists the choice and updates the document language", () => {
    writeLanguage("en");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
    expect(readLanguage()).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("survives a storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readLanguage()).toBe("es");
    expect(() => writeLanguage("en")).not.toThrow();
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("theme preference", () => {
  it("defaults to system and ignores unknown stored values", () => {
    expect(readTheme()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    expect(readTheme()).toBe("system");
  });

  it("persists light, dark and system", () => {
    for (const theme of ["light", "dark", "system"] as const) {
      writeTheme(theme);
      expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(theme);
      expect(readTheme()).toBe(theme);
    }
  });

  it("toggles the .dark class for explicit choices", () => {
    applyTheme("dark");
    expect(document.documentElement).toHaveClass("dark");
    applyTheme("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("follows the OS preference for system", () => {
    stubMatchMedia(true);
    applyTheme("system");
    expect(document.documentElement).toHaveClass("dark");
    stubMatchMedia(false);
    applyTheme("system");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("falls back to light when matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);
    applyTheme("system");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("re-applies system when the OS preference changes, until stopped", () => {
    const media = stubMatchMedia(false);
    applyTheme("system");
    const stop = watchSystemTheme();
    media.flip(true);
    expect(document.documentElement).toHaveClass("dark");
    writeTheme("light");
    media.flip(true);
    expect(document.documentElement).not.toHaveClass("dark");
    stop();
    expect(media.listeners.size).toBe(0);
  });

  it("writeTheme applies the theme too", () => {
    writeTheme("dark");
    expect(document.documentElement).toHaveClass("dark");
  });

  it("survives a storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readTheme()).toBe("system");
    expect(() => writeTheme("dark")).not.toThrow();
    expect(document.documentElement).toHaveClass("dark");
  });
});
