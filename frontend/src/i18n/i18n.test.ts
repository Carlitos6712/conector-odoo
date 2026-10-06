import { createI18n, resources } from "@/i18n";

function flatKeys(tree: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    value && typeof value === "object"
      ? flatKeys(value as Record<string, unknown>, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("i18n", () => {
  it("defaults to Spanish", async () => {
    const i18n = await createI18n();
    expect(i18n.language).toBe("es");
    expect(i18n.t("login.submit")).toBe("Entrar");
  });

  it("falls back to Spanish for keys missing in the active language", async () => {
    const i18n = await createI18n("en", {
      es: { translation: { only: { spanish: "Solo español" } } },
      en: { translation: {} },
    });
    expect(i18n.t("only.spanish")).toBe("Solo español");
  });

  it("returns the key itself when no language defines it", async () => {
    const i18n = await createI18n();
    expect(i18n.t("does.not.exist")).toBe("does.not.exist");
  });

  it("keeps English in key parity with Spanish", () => {
    expect(flatKeys(resources.en.translation).sort()).toEqual(
      flatKeys(resources.es.translation).sort(),
    );
  });

  it("interpolates values", async () => {
    const i18n = await createI18n();
    expect(i18n.t("login.errors.rate_limited", { seconds: 30 })).toContain("30");
  });
});
