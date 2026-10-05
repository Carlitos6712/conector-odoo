import type { Run, RunStatus } from "@/features/runs/types";

export const isActiveStatus = (status: RunStatus): boolean =>
  status === "queued" || status === "running";

/** Poll once a second while a run moves, never once it is finished. */
export const runRefetchInterval = (run: Run | undefined): number | false =>
  run && isActiveStatus(run.status) ? 1000 : false;

/** The most recently started real run of each job (dry runs change nothing, so they are skipped). */
export function latestRunByJob(runs: readonly Run[]): Map<number, Run> {
  const latest = new Map<number, Run>();
  for (const run of runs) {
    if (run.dry_run) continue;
    const current = latest.get(run.job_id);
    if (current === undefined || Date.parse(run.started_at) > Date.parse(current.started_at)) {
      latest.set(run.job_id, run);
    }
  }
  return latest;
}
