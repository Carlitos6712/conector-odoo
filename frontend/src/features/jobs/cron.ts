/**
 * Classic 5-field numeric cron, evaluated in UTC. Mirrors the backend (`validate_cron` in
 * `domain/sync.py` and `next_fire` in `domain/cron.py`): a wildcard, `a`, `a-b`, steps (`n`
 * after a slash on a wildcard, a range or a start value), comma lists; weekday 0 and 7 are Sunday; when both day-of-month and weekday are restricted
 * (neither starts with `*`) a day matches if EITHER does (Vixie cron).
 */
export type CronFieldName = "minute" | "hour" | "dayOfMonth" | "month" | "dayOfWeek";

export interface CronIssue {
  code: "fields" | "syntax" | "step" | "range";
  field?: CronFieldName;
}

const FIELDS: readonly { name: CronFieldName; low: number; high: number }[] = [
  { name: "minute", low: 0, high: 59 },
  { name: "hour", low: 0, high: 23 },
  { name: "dayOfMonth", low: 1, high: 31 },
  { name: "month", low: 1, high: 12 },
  { name: "dayOfWeek", low: 0, high: 7 },
];

const ITEM = /^(\*|\d+(?:-\d+)?)(?:\/(\d+))?$/;
const MAX_DAYS = 366 * 9; // same search horizon as the backend

const split = (expression: string): string[] => expression.trim().split(/\s+/).filter(Boolean);

/** `null` when the expression is acceptable to the backend, otherwise the first problem. */
export function validateCron(expression: string): CronIssue | null {
  const parts = split(expression);
  if (parts.length !== 5) return { code: "fields" };
  for (const [index, part] of parts.entries()) {
    const { name, low, high } = FIELDS[index]!;
    for (const item of part.split(",")) {
      const match = ITEM.exec(item);
      if (match === null) return { code: "syntax", field: name };
      if (match[2] !== undefined && Number(match[2]) < 1) return { code: "step", field: name };
      if (match[1] !== "*") {
        const bounds = match[1]!.split("-").map(Number);
        const sorted = bounds.every((n, i) => i === 0 || n >= bounds[i - 1]!);
        if (bounds.some((n) => n < low || n > high) || !sorted) {
          return { code: "range", field: name };
        }
      }
    }
  }
  return null;
}

function expand(field: string, low: number, high: number): Set<number> {
  const values = new Set<number>();
  for (const item of field.split(",")) {
    const [base = "", stepText] = item.split("/");
    const step = stepText === undefined ? 1 : Number(stepText);
    let start: number;
    let end: number;
    if (base === "*") {
      [start, end] = [low, high];
    } else if (base.includes("-")) {
      const [first = "", last = ""] = base.split("-");
      [start, end] = [Number(first), Number(last)];
    } else {
      start = Number(base);
      end = stepText === undefined ? start : high;
    }
    for (let value = start; value <= end; value += step) values.add(value);
  }
  return values;
}

/**
 * The next `count` fire times strictly after `after`, in UTC. Empty for an invalid expression
 * or one that never fires within about nine years (for example February 31).
 */
export function nextFires(expression: string, after: Date, count: number): Date[] {
  if (validateCron(expression) !== null || count < 1) return [];
  const parts = split(expression);
  const [minutes, hours, doms, months, rawDows] = parts.map((part, i) =>
    expand(part, FIELDS[i]!.low, FIELDS[i]!.high),
  ) as [Set<number>, Set<number>, Set<number>, Set<number>, Set<number>];
  const dows = new Set([...rawDows].map((d) => d % 7));
  const domAny = parts[2]!.startsWith("*");
  const dowAny = parts[4]!.startsWith("*");
  const sortedHours = [...hours].sort((a, b) => a - b);
  const sortedMinutes = [...minutes].sort((a, b) => a - b);

  const start = new Date(Math.floor(after.getTime() / 60_000) * 60_000 + 60_000);
  const day = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate()));
  const fires: Date[] = [];
  for (let i = 0; i < MAX_DAYS && fires.length < count; i++) {
    const domOk = doms.has(day.getUTCDate());
    const dowOk = dows.has(day.getUTCDay());
    const dayOk = domAny || dowAny ? domOk && dowOk : domOk || dowOk;
    if (months.has(day.getUTCMonth() + 1) && dayOk) {
      for (const hour of sortedHours) {
        for (const minute of sortedMinutes) {
          const candidate = new Date(
            Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour, minute),
          );
          if (candidate >= start && fires.length < count) fires.push(candidate);
        }
      }
    }
    day.setUTCDate(day.getUTCDate() + 1);
  }
  return fires;
}

// -- human description -------------------------------------------------------------------------

export type CronDescription =
  | { kind: "everyMinute" }
  | { kind: "everyNMinutes"; n: number }
  | { kind: "hourly"; minute: number }
  | { kind: "daily"; time: string }
  | { kind: "weekly"; days: number[]; time: string }
  | { kind: "custom" };

const INT = /^\d+$/;
const DOW_LIST = /^[0-7](,[0-7])*$/;
const pad = (n: number) => String(n).padStart(2, "0");

const daysOf = (field: string): number[] =>
  [...new Set(field.split(",").map((d) => Number(d) % 7))].sort((a, b) => a - b);

/** A structured description for the common shapes (the UI translates it); null when invalid. */
export function describeCron(expression: string): CronDescription | null {
  if (validateCron(expression) !== null) return null;
  const [minute = "", hour = "", dom = "", month = "", dow = ""] = split(expression);
  const everyDay = dom === "*" && month === "*";
  if (everyDay && dow === "*") {
    if (hour === "*" && minute === "*") return { kind: "everyMinute" };
    const step = /^\*\/(\d+)$/.exec(minute);
    if (hour === "*" && step) return { kind: "everyNMinutes", n: Number(step[1]) };
    if (hour === "*" && INT.test(minute)) return { kind: "hourly", minute: Number(minute) };
    if (INT.test(hour) && INT.test(minute)) {
      return { kind: "daily", time: `${pad(Number(hour))}:${pad(Number(minute))}` };
    }
  }
  if (everyDay && DOW_LIST.test(dow) && INT.test(hour) && INT.test(minute)) {
    return {
      kind: "weekly",
      days: daysOf(dow),
      time: `${pad(Number(hour))}:${pad(Number(minute))}`,
    };
  }
  return { kind: "custom" };
}

// -- presets -----------------------------------------------------------------------------------

export type CronPreset =
  | { kind: "hourly"; minute: number }
  | { kind: "daily"; hour: number; minute: number }
  | { kind: "weekly"; days: number[]; hour: number; minute: number };

const inRange = (n: number, low: number, high: number) =>
  Number.isInteger(n) && n >= low && n <= high;

/** The expression of a preset, or null when it is incomplete or out of range. */
export function buildCron(preset: CronPreset): string | null {
  if (!inRange(preset.minute, 0, 59)) return null;
  if (preset.kind === "hourly") return `${preset.minute} * * * *`;
  if (!inRange(preset.hour, 0, 23)) return null;
  if (preset.kind === "daily") return `${preset.minute} ${preset.hour} * * *`;
  if (preset.days.length === 0 || !preset.days.every((d) => inRange(d, 0, 6))) return null;
  const days = [...new Set(preset.days)].sort((a, b) => a - b);
  return `${preset.minute} ${preset.hour} * * ${days.join(",")}`;
}

/** The preset an expression was built from, so the editor can show it again; else null. */
export function detectPreset(expression: string): CronPreset | null {
  if (validateCron(expression) !== null) return null;
  const [minute = "", hour = "", dom = "", month = "", dow = ""] = split(expression);
  if (!INT.test(minute) || dom !== "*" || month !== "*") return null;
  if (hour === "*" && dow === "*") return { kind: "hourly", minute: Number(minute) };
  if (!INT.test(hour)) return null;
  if (dow === "*") return { kind: "daily", hour: Number(hour), minute: Number(minute) };
  if (DOW_LIST.test(dow)) {
    return { kind: "weekly", days: daysOf(dow), hour: Number(hour), minute: Number(minute) };
  }
  return null;
}
