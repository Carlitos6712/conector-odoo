import { formatRelativeTime } from "@/features/connections/relative";

const NOW = new Date("2026-03-10T12:00:00Z").getTime();

describe("formatRelativeTime", () => {
  it.each([
    ["2026-03-10T11:59:40Z", "ahora"],
    ["2026-03-10T11:30:00Z", "hace 30 minutos"],
    ["2026-03-10T09:00:00Z", "hace 3 horas"],
    ["2026-03-07T12:00:00Z", "hace 3 días"],
    ["2025-12-10T12:00:00Z", "hace 3 meses"],
  ])("renders %s in Spanish", (iso, expected) => {
    expect(formatRelativeTime(iso, NOW, "es")).toBe(expected);
  });

  it("clamps timestamps slightly in the future (clock skew) to now", () => {
    expect(formatRelativeTime("2026-03-10T12:00:30Z", NOW, "es")).toBe("ahora");
  });

  it("falls back to the raw text when the timestamp cannot be parsed", () => {
    expect(formatRelativeTime("not-a-date", NOW, "es")).toBe("not-a-date");
  });

  it("follows the requested language", () => {
    expect(formatRelativeTime("2026-03-10T09:00:00Z", NOW, "en")).toBe("3 hours ago");
  });
});
