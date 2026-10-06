import type { Job } from "@/features/jobs/types";
import type { Run } from "@/features/runs/types";

/** Test fixtures shared by the jobs suites (never imported by app code). */
export function jobFixture(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    name: "Clientes a Odoo",
    source: { profile_id: 1, resource: "clients" },
    target: { profile_id: 2, resource: "res.partner" },
    mapping: { name: "clients-to-partner", version: null },
    reverse_mapping: null,
    direction: "a_to_b",
    trigger: { kind: "manual" },
    record_filter: { equals: {}, since: null, raw: null },
    reverse_record_filter: { equals: {}, since: null, raw: null },
    batch_size: 100,
    upsert_key: "xref",
    conflict_rule: "source_wins",
    source_updated_field: null,
    target_updated_field: null,
    enabled: true,
    next_fire: null,
    ...overrides,
  };
}

export function runFixture(overrides: Partial<Run> = {}): Run {
  return {
    id: 41,
    job_id: 7,
    status: "succeeded",
    trigger: "manual",
    dry_run: false,
    counters: { created: 3, updated: 1, skipped: 2, failed: 0, conflicts: 0, processed: 6 },
    started_at: "2026-03-01T10:00:00Z",
    finished_at: "2026-03-01T10:00:05Z",
    duration_seconds: 5,
    heartbeat_at: "2026-03-01T10:00:05Z",
    parent_run_id: null,
    error: null,
    cancel_requested: false,
    error_count: 0,
    ...overrides,
  };
}
