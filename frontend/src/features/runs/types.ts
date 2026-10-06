/** Wire shapes of `/admin/api/runs` (see `admin_api/schemas/runs.py`). F6 extends this module. */
export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";

export interface RunCounters {
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  conflicts: number;
  processed: number;
}

export interface Run {
  id: number;
  job_id: number;
  status: RunStatus;
  trigger: string;
  dry_run: boolean;
  counters: RunCounters;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  heartbeat_at: string | null;
  parent_run_id: number | null;
  error: string | null;
  cancel_requested: boolean;
  error_count: number | null;
}

/** `GET /runs/{id}`: the run plus its sample of mapped records (a dry run's preview). */
export interface RunDetail extends Run {
  options: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  sample: Record<string, unknown>[];
}

export interface RunError {
  id: number;
  run_id: number;
  record_ref: string | null;
  message: string;
  side: string;
  kind: string;
  retryable: boolean;
  retried: boolean;
  payload: Record<string, unknown> | null;
}

export interface RunErrorPage {
  items: RunError[];
  total: number;
}
