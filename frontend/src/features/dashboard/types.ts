import type { Run } from "@/features/runs/types";

/** `DashboardOut.scheduled[]`: an enabled schedule job and the scheduler's next fire. */
export interface ScheduledJob {
  job_id: number;
  name: string;
  cron: string;
  /** UTC ISO; null when the scheduler is off or does not know the job. */
  next_fire: string | null;
}

/** Wire shape of `GET /admin/api/dashboard` (see `admin_api/schemas/runs.py`). */
export interface Dashboard {
  profiles: number;
  mappings: number;
  jobs_total: number;
  jobs_enabled: number;
  /** Runs started in the last 24 hours, keyed by status (capped at 1000 runs server-side). */
  runs_last_24h: Record<string, number>;
  active_runs: Run[];
  recent_runs: Run[];
  recent_failures: Run[];
  scheduled: ScheduledJob[];
}
