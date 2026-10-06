import {
  buildCron,
  describeCron,
  detectPreset,
  nextFires,
  validateCron,
} from "@/features/jobs/cron";

const iso = (dates: Date[]) => dates.map((d) => d.toISOString());
const at = (text: string) => new Date(text);

describe("validateCron", () => {
  it.each(["* * * * *", "*/15 0-6 1,15 * 1-5", "0 9 * * 7", "5/10 * * * *", "  0   9 * * *  "])(
    "accepts %j",
    (expression) => expect(validateCron(expression)).toBeNull(),
  );

  it("needs exactly five fields", () => {
    expect(validateCron("* * * *")).toEqual({ code: "fields" });
    expect(validateCron("@daily")).toEqual({ code: "fields" });
    expect(validateCron("* * * * * *")).toEqual({ code: "fields" });
    expect(validateCron("")).toEqual({ code: "fields" });
  });

  it.each([
    ["60 * * * *", "minute"],
    ["* 24 * * *", "hour"],
    ["* * 0 * *", "dayOfMonth"],
    ["* * 32 * *", "dayOfMonth"],
    ["* * * 13 *", "month"],
    ["* * * 0 *", "month"],
    ["* * * * 8", "dayOfWeek"],
    ["5-1 * * * *", "minute"],
  ])("rejects %j as out of range", (expression, field) => {
    expect(validateCron(expression)).toEqual({ code: "range", field });
  });

  it("rejects a zero step and names the field", () => {
    expect(validateCron("*/0 * * * *")).toEqual({ code: "step", field: "minute" });
  });

  it("rejects names, question marks and other non numeric syntax", () => {
    expect(validateCron("* * * * MON")).toEqual({ code: "syntax", field: "dayOfWeek" });
    expect(validateCron("? * * * *")).toEqual({ code: "syntax", field: "minute" });
    expect(validateCron("1- * * * *")).toEqual({ code: "syntax", field: "minute" });
    expect(validateCron("1,,2 * * * *")).toEqual({ code: "syntax", field: "minute" });
  });
});

describe("nextFires", () => {
  it("lists the next fire times strictly after the given instant (UTC)", () => {
    expect(iso(nextFires("*/15 * * * *", at("2026-01-01T10:07:30Z"), 3))).toEqual([
      "2026-01-01T10:15:00.000Z",
      "2026-01-01T10:30:00.000Z",
      "2026-01-01T10:45:00.000Z",
    ]);
    expect(iso(nextFires("*/15 * * * *", at("2026-01-01T10:15:00Z"), 1))).toEqual([
      "2026-01-01T10:30:00.000Z",
    ]);
  });

  it("rolls over days for a daily schedule", () => {
    expect(iso(nextFires("30 9 * * *", at("2026-01-01T09:30:00Z"), 3))).toEqual([
      "2026-01-02T09:30:00.000Z",
      "2026-01-03T09:30:00.000Z",
      "2026-01-04T09:30:00.000Z",
    ]);
  });

  it("treats weekday 0 and 7 as Sunday", () => {
    const expected = [
      "2026-01-04T08:00:00.000Z",
      "2026-01-11T08:00:00.000Z",
      "2026-01-18T08:00:00.000Z",
    ];
    expect(iso(nextFires("0 8 * * 0", at("2026-01-01T00:00:00Z"), 3))).toEqual(expected);
    expect(iso(nextFires("0 8 * * 7", at("2026-01-01T00:00:00Z"), 3))).toEqual(expected);
  });

  it("matches either day of month or weekday when both are restricted (Vixie OR)", () => {
    // 2026-01-01 is a Thursday: Fridays are the 2nd and 9th, the 13th is a Tuesday.
    expect(iso(nextFires("0 0 13 * 5", at("2026-01-01T00:00:00Z"), 3))).toEqual([
      "2026-01-02T00:00:00.000Z",
      "2026-01-09T00:00:00.000Z",
      "2026-01-13T00:00:00.000Z",
    ]);
  });

  it("requires both when one of the day fields is a wildcard", () => {
    expect(iso(nextFires("0 0 13 * *", at("2026-01-01T00:00:00Z"), 3))).toEqual([
      "2026-01-13T00:00:00.000Z",
      "2026-02-13T00:00:00.000Z",
      "2026-03-13T00:00:00.000Z",
    ]);
    // "*/2" starts with "*", so it counts as a wildcard like in the backend.
    expect(nextFires("0 0 */2 * 5", at("2026-01-01T00:00:00Z"), 1)).toHaveLength(1);
  });

  it("honours month lists and step ranges", () => {
    expect(iso(nextFires("0 0 1 3,6 *", at("2026-01-01T00:00:00Z"), 3))).toEqual([
      "2026-03-01T00:00:00.000Z",
      "2026-06-01T00:00:00.000Z",
      "2027-03-01T00:00:00.000Z",
    ]);
    expect(iso(nextFires("10/20 5 * * *", at("2026-01-01T00:00:00Z"), 3))).toEqual([
      "2026-01-01T05:10:00.000Z",
      "2026-01-01T05:30:00.000Z",
      "2026-01-01T05:50:00.000Z",
    ]);
  });

  it("returns nothing for a date that does not exist or an invalid expression", () => {
    expect(nextFires("0 0 31 2 *", at("2026-01-01T00:00:00Z"), 3)).toEqual([]);
    expect(nextFires("nope", at("2026-01-01T00:00:00Z"), 3)).toEqual([]);
  });

  it("finds leap days within the search horizon", () => {
    const fires = iso(nextFires("0 0 29 2 *", at("2026-01-01T00:00:00Z"), 2));
    expect(fires).toEqual(["2028-02-29T00:00:00.000Z", "2032-02-29T00:00:00.000Z"]);
  });
});

describe("describeCron", () => {
  it("recognises the common shapes", () => {
    expect(describeCron("* * * * *")).toEqual({ kind: "everyMinute" });
    expect(describeCron("*/5 * * * *")).toEqual({ kind: "everyNMinutes", n: 5 });
    expect(describeCron("15 * * * *")).toEqual({ kind: "hourly", minute: 15 });
    expect(describeCron("30 9 * * *")).toEqual({ kind: "daily", time: "09:30" });
    expect(describeCron("0 8 * * 1,3,5")).toEqual({
      kind: "weekly",
      days: [1, 3, 5],
      time: "08:00",
    });
  });

  it("folds weekday 7 into Sunday", () => {
    expect(describeCron("0 8 * * 7")).toEqual({ kind: "weekly", days: [0], time: "08:00" });
    expect(describeCron("0 8 * * 0,7")).toEqual({ kind: "weekly", days: [0], time: "08:00" });
  });

  it("falls back to custom for anything else and null when invalid", () => {
    expect(describeCron("*/10 9-17 * * 1-5")).toEqual({ kind: "custom" });
    expect(describeCron("0 0 1 * *")).toEqual({ kind: "custom" });
    expect(describeCron("nope")).toBeNull();
  });
});

describe("presets", () => {
  it("builds expressions from presets", () => {
    expect(buildCron({ kind: "hourly", minute: 5 })).toBe("5 * * * *");
    expect(buildCron({ kind: "daily", hour: 9, minute: 30 })).toBe("30 9 * * *");
    expect(buildCron({ kind: "weekly", days: [5, 1, 3, 1], hour: 8, minute: 0 })).toBe(
      "0 8 * * 1,3,5",
    );
  });

  it("refuses incomplete or out of range presets", () => {
    expect(buildCron({ kind: "weekly", days: [], hour: 8, minute: 0 })).toBeNull();
    expect(buildCron({ kind: "daily", hour: 24, minute: 0 })).toBeNull();
    expect(buildCron({ kind: "hourly", minute: 60 })).toBeNull();
    expect(buildCron({ kind: "daily", hour: 1.5, minute: 0 })).toBeNull();
  });

  it("detects the preset behind an expression", () => {
    expect(detectPreset("30 9 * * *")).toEqual({ kind: "daily", hour: 9, minute: 30 });
    expect(detectPreset("5 * * * *")).toEqual({ kind: "hourly", minute: 5 });
    expect(detectPreset("0 8 * * 1,3,5")).toEqual({
      kind: "weekly",
      days: [1, 3, 5],
      hour: 8,
      minute: 0,
    });
    expect(detectPreset("0 8 * * 7")).toEqual({ kind: "weekly", days: [0], hour: 8, minute: 0 });
  });

  it("leaves everything else to the advanced editor", () => {
    expect(detectPreset("*/5 * * * *")).toBeNull();
    expect(detectPreset("0 8 1 * *")).toBeNull();
    expect(detectPreset("0 8 * * 1-5")).toBeNull();
    expect(detectPreset("nope")).toBeNull();
  });
});
