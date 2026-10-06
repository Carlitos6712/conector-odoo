const UNITS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** Under this many seconds the age is just "a moment ago" (also absorbs small clock skew). */
const JUST_NOW_SECONDS = 45;

/**
 * "hace 3 horas" style age of an ISO timestamp relative to `now` (ms). Future timestamps are
 * clamped to now; text that is not a date is returned unchanged.
 */
export function formatRelativeTime(iso: string, now: number, locale: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  const formatter = new Intl.RelativeTimeFormat(locale, { numeric: "always" });
  if (seconds < JUST_NOW_SECONDS) {
    return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(0, "second");
  }
  for (const [unit, size] of UNITS) {
    if (seconds >= size) return formatter.format(-Math.floor(seconds / size), unit);
  }
  return formatter.format(-1, "minute");
}
