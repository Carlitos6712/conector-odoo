import type { ActiveOdoo } from "@/features/connections/types";
import type { Dashboard, ScheduledJob } from "@/features/dashboard/types";
import { nextFires } from "@/features/jobs/cron";
import type { Job } from "@/features/jobs/types";
import { isStale, listRefetchInterval } from "@/features/runs/policy";
import { isActiveStatus } from "@/features/runs/summary";
import type { Run } from "@/features/runs/types";

/** Same policy as the runs list: poll only while a run is active and the tab is in front. */
export const dashboardRefetchInterval = (
  data: Dashboard | undefined,
  hidden: boolean,
): number | false => listRefetchInterval(data?.active_runs, hidden);

export interface DayBucket {
  /** Local calendar day, `YYYY-MM-DD`. */
  day: string;
  succeeded: number;
  partial: number;
  failed: number;
  /** Cancelled and still-active runs. */
  other: number;
  total: number;
}

const dayKey = (date: Date): string =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

/**
 * Real runs per local day for the last `days` days (today included), oldest first. Dry runs
 * change nothing, so they are not counted.
 */
export function runsByDay(runs: readonly Run[], now: Date, days: number): DayBucket[] {
  const buckets = new Map<string, DayBucket>();
  for (let offset = days - 1; offset >= 0; offset--) {
    const day = dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset));
    buckets.set(day, { day, succeeded: 0, partial: 0, failed: 0, other: 0, total: 0 });
  }
  for (const run of runs) {
    if (run.dry_run) continue;
    const started = new Date(run.started_at);
    if (Number.isNaN(started.getTime())) continue;
    const bucket = buckets.get(dayKey(started));
    if (!bucket) continue;
    if (run.status === "succeeded") bucket.succeeded++;
    else if (run.status === "partial") bucket.partial++;
    else if (run.status === "failed") bucket.failed++;
    else bucket.other++;
    bucket.total++;
  }
  return [...buckets.values()];
}

export type AttentionItem =
  | { kind: "failedRun"; run: Run }
  | { kind: "staleRun"; run: Run }
  | { kind: "repeatedFailures"; jobId: number; name: string; count: number };

/** A job whose latest real runs failed this many times in a row needs a look. */
export const REPEATED_FAILURES = 2;

interface AttentionInput {
  failures: readonly Run[];
  active: readonly Run[];
  /** Latest runs, newest first. */
  recent: readonly Run[];
  jobs: readonly Job[];
  now: number;
}

/** Consecutive failed runs at the head of a job's history; cancelled runs are skipped. */
function failureStreak(runs: readonly Run[]): number {
  let streak = 0;
  for (const run of runs) {
    if (run.status === "cancelled") continue;
    if (run.status !== "failed") break;
    streak++;
  }
  return streak;
}

export function attentionItems({
  failures,
  active,
  recent,
  jobs,
  now,
}: AttentionInput): AttentionItem[] {
  const items: AttentionItem[] = [];
  for (const run of failures) items.push({ kind: "failedRun", run });
  for (const run of active) if (isStale(run, now)) items.push({ kind: "staleRun", run });
  for (const job of jobs) {
    const history = recent
      .filter((run) => run.job_id === job.id && !run.dry_run && !isActiveStatus(run.status))
      .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
    const count = failureStreak(history);
    if (count >= REPEATED_FAILURES) {
      items.push({ kind: "repeatedFailures", jobId: job.id, name: job.name, count });
    }
  }
  return items;
}

export interface NextFire {
  at: string;
  /** True when computed here from the cron because the scheduler reported none. */
  estimated: boolean;
}

export function nextFireOf(scheduled: ScheduledJob, now: Date): NextFire | null {
  if (scheduled.next_fire) return { at: scheduled.next_fire, estimated: false };
  const [next] = nextFires(scheduled.cron, now, 1);
  return next ? { at: next.toISOString(), estimated: true } : null;
}

/**
 * What is wrong with the Odoo connection, if anything: nothing connected (the data API answers
 * 503) or a fallback after the stored profile failed to load. Unknown (not loaded) raises nothing.
 */
export function odooAttention(active: ActiveOdoo | undefined): "none" | "fallback" | null {
  if (!active) return null;
  if (active.source === "none") return "none";
  return active.status === "fallback" ? "fallback" : null;
}
