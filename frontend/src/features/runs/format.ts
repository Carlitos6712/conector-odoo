import type { Run } from "@/features/runs/types";

/** Compact duration for tables: `5 s`, `1 min 5 s`, `1 h 2 min`; a dash when unknown. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const total = Math.round(Math.max(seconds, 0));
  if (total < 1) return "<1 s";
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} h`);
  if (minutes > 0) parts.push(`${minutes} min`);
  // Seconds only matter below an hour; "1 h 2 min 5 s" is noise in a table.
  if (secs > 0 && hours === 0) parts.push(`${secs} s`);
  return parts.join(" ");
}

/** What the API reports for a finished run; elapsed time against `now` while it is still going. */
export function runDurationSeconds(run: Run, now: number): number | null {
  if (run.duration_seconds !== null) return run.duration_seconds;
  const started = Date.parse(run.started_at);
  return Number.isNaN(started) ? null : Math.max((now - started) / 1000, 0);
}
