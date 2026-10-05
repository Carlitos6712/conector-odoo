import { runFixture } from "@/features/jobs/fixtures";
import type { RunDetail, RunError } from "@/features/runs/types";

/** Test fixtures shared by the runs suites (never imported by app code). */
export function runDetailFixture(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    ...runFixture(),
    options: {},
    checkpoint: {},
    sample: [],
    ...overrides,
  };
}

export function runErrorFixture(overrides: Partial<RunError> = {}): RunError {
  return {
    id: 1,
    run_id: 41,
    record_ref: "c-100",
    message: "Odoo rejected the record",
    side: "source",
    kind: "rejected",
    retryable: true,
    retried: false,
    payload: { name: "Ana", api_key: "***" },
    ...overrides,
  };
}
