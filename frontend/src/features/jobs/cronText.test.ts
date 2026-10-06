import { cronSentence } from "@/features/jobs/cronText";
import { createI18n } from "@/i18n";

describe("cronSentence", () => {
  it.each([
    ["* * * * *", "Cada minuto"],
    ["*/5 * * * *", "Cada 5 minutos"],
    ["15 * * * *", "Cada hora, en el minuto 15"],
    ["30 9 * * *", "Todos los días a las 09:30 UTC"],
    ["0 8 * * 1,3,5", "Los lunes, miércoles y viernes a las 08:00 UTC"],
    ["0 8 * * 0", "Los domingos a las 08:00 UTC"],
    ["0 8 * * 7,1", "Los domingos y lunes a las 08:00 UTC"],
    ["*/10 9-17 * * 1-5", "Expresión personalizada (UTC): */10 9-17 * * 1-5"],
  ])("describes %j in Spanish", async (cron, sentence) => {
    const i18n = await createI18n("es");
    expect(cronSentence(i18n.t, cron)).toBe(sentence);
  });

  it("speaks English too", async () => {
    const i18n = await createI18n("en");
    expect(cronSentence(i18n.t, "30 9 * * *")).toBe("Every day at 09:30 UTC");
  });

  it("returns null for an invalid expression", async () => {
    const i18n = await createI18n("es");
    expect(cronSentence(i18n.t, "nope")).toBeNull();
  });
});
