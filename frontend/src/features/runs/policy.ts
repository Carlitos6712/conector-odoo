import { isActiveStatus } from "@/features/runs/summary";
import type { Run, RunError, RunStatus } from "@/features/runs/types";

/** The backend treats an active run silent for this long as crashed (`RunnerConfig.stale_after`). */
export const STALE_AFTER_MS = 15 * 60_000;
const LIST_POLL_MS = 3000;

export type StatusGroup = "active" | "ok" | "attention" | "stopped";

export function statusGroup(status: RunStatus): StatusGroup {
  if (isActiveStatus(status)) return "active";
  if (status === "succeeded") return "ok";
  if (status === "cancelled") return "stopped";
  return "attention";
}

/** Poll the list only while a visible run moves and the tab is in front. */
export function listRefetchInterval(
  runs: readonly Run[] | undefined,
  hidden: boolean,
): number | false {
  if (hidden || !runs) return false;
  return runs.some((run) => isActiveStatus(run.status)) ? LIST_POLL_MS : false;
}

/** An active run whose last heartbeat (or start) is older than the stale window. */
export function isStale(run: Run, now: number): boolean {
  if (!isActiveStatus(run.status)) return false;
  const last = Date.parse(run.heartbeat_at ?? run.started_at);
  return !Number.isNaN(last) && now - last > STALE_AFTER_MS;
}

export const canCancel = (run: Run): boolean => isActiveStatus(run.status) && !run.cancel_requested;

/** Mirrors `SyncRunner.prepare_resume`: failed, cancelled, or active but crashed. */
export const canResume = (run: Run, now: number): boolean =>
  run.status === "failed" || run.status === "cancelled" || isStale(run, now);

/** The API refuses with 409 when nothing is retryable (conflicts are never retried). */
export const canRetryFailed = (run: Run): boolean =>
  !isActiveStatus(run.status) && (run.error_count ?? 0) > 0;

export interface RunClientFilters {
  trigger: string;
  dryRun: "" | "yes" | "no";
}

/** `GET /runs` filters by job, status and date only; these two apply to the loaded page. */
export function filterRuns(runs: readonly Run[], filters: RunClientFilters): Run[] {
  return runs.filter(
    (run) =>
      (filters.trigger === "" || run.trigger === filters.trigger) &&
      (filters.dryRun === "" || run.dry_run === (filters.dryRun === "yes")),
  );
}

export interface ErrorClientFilters {
  kind: string;
  retryable: "" | "yes" | "no";
}

/** The errors endpoint has no kind/retryable filter; these apply to the loaded page. */
export function filterErrors(errors: readonly RunError[], filters: ErrorClientFilters): RunError[] {
  return errors.filter(
    (error) =>
      (filters.kind === "" || error.kind === filters.kind) &&
      (filters.retryable === "" || error.retryable === (filters.retryable === "yes")),
  );
}
