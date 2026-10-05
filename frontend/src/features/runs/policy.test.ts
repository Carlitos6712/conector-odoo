import { runFixture } from "@/features/jobs/fixtures";
import {
  canCancel,
  canResume,
  canRetryFailed,
  filterErrors,
  filterRuns,
  isStale,
  listRefetchInterval,
  STALE_AFTER_MS,
  statusGroup,
} from "@/features/runs/policy";
import type { RunError } from "@/features/runs/types";

const NOW = Date.parse("2026-03-01T12:00:00Z");
const minutesAgo = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

describe("statusGroup", () => {
  it("groups statuses by what the operator should do about them", () => {
    expect(statusGroup("queued")).toBe("active");
    expect(statusGroup("running")).toBe("active");
    expect(statusGroup("succeeded")).toBe("ok");
    expect(statusGroup("partial")).toBe("attention");
    expect(statusGroup("failed")).toBe("attention");
    expect(statusGroup("cancelled")).toBe("stopped");
  });
});

describe("listRefetchInterval", () => {
  const running = runFixture({ status: "running" });
  const done = runFixture({ status: "succeeded" });

  it("polls while any visible run is active", () => {
    expect(listRefetchInterval([done, running], false)).toBe(3000);
    expect(listRefetchInterval([runFixture({ status: "queued" })], false)).toBe(3000);
  });

  it("stops when everything is finished, the list is unknown or the tab is hidden", () => {
    expect(listRefetchInterval([done], false)).toBe(false);
    expect(listRefetchInterval(undefined, false)).toBe(false);
    expect(listRefetchInterval([], false)).toBe(false);
    expect(listRefetchInterval([running], true)).toBe(false);
  });
});

describe("isStale", () => {
  it("is only true for an active run that stopped heartbeating for 15 minutes", () => {
    expect(STALE_AFTER_MS).toBe(15 * 60_000);
    const quiet = runFixture({ status: "running", heartbeat_at: minutesAgo(16) });
    expect(isStale(quiet, NOW)).toBe(true);
    expect(isStale({ ...quiet, heartbeat_at: minutesAgo(14) }, NOW)).toBe(false);
    expect(isStale({ ...quiet, status: "failed" }, NOW)).toBe(false);
  });

  it("falls back to the start time when there was never a heartbeat", () => {
    const run = runFixture({ status: "queued", heartbeat_at: null, started_at: minutesAgo(30) });
    expect(isStale(run, NOW)).toBe(true);
  });
});

describe("run actions", () => {
  it("cancels only active runs that were not asked to stop yet", () => {
    expect(canCancel(runFixture({ status: "running" }))).toBe(true);
    expect(canCancel(runFixture({ status: "running", cancel_requested: true }))).toBe(false);
    expect(canCancel(runFixture({ status: "succeeded" }))).toBe(false);
  });

  it("resumes failed and cancelled runs and active runs that went quiet", () => {
    expect(canResume(runFixture({ status: "failed" }), NOW)).toBe(true);
    expect(canResume(runFixture({ status: "cancelled" }), NOW)).toBe(true);
    expect(canResume(runFixture({ status: "succeeded" }), NOW)).toBe(false);
    expect(canResume(runFixture({ status: "partial" }), NOW)).toBe(false);
    const alive = runFixture({ status: "running", heartbeat_at: minutesAgo(1) });
    expect(canResume(alive, NOW)).toBe(false);
    expect(canResume({ ...alive, heartbeat_at: minutesAgo(20) }, NOW)).toBe(true);
  });

  it("retries failed records of a finished run that recorded errors", () => {
    expect(canRetryFailed(runFixture({ status: "partial", error_count: 2 }))).toBe(true);
    expect(canRetryFailed(runFixture({ status: "failed", error_count: 1 }))).toBe(true);
    expect(canRetryFailed(runFixture({ status: "partial", error_count: 0 }))).toBe(false);
    expect(canRetryFailed(runFixture({ status: "partial", error_count: null }))).toBe(false);
    expect(canRetryFailed(runFixture({ status: "running", error_count: 2 }))).toBe(false);
  });
});

describe("filterRuns", () => {
  const runs = [
    runFixture({ id: 1, trigger: "manual", dry_run: false }),
    runFixture({ id: 2, trigger: "schedule", dry_run: false }),
    runFixture({ id: 3, trigger: "webhook", dry_run: true }),
  ];

  it("keeps everything without filters", () => {
    expect(filterRuns(runs, { trigger: "", dryRun: "" })).toHaveLength(3);
  });

  it("filters by trigger and by dry-run flag", () => {
    expect(filterRuns(runs, { trigger: "schedule", dryRun: "" }).map((r) => r.id)).toEqual([2]);
    expect(filterRuns(runs, { trigger: "", dryRun: "yes" }).map((r) => r.id)).toEqual([3]);
    expect(filterRuns(runs, { trigger: "", dryRun: "no" }).map((r) => r.id)).toEqual([1, 2]);
  });
});

describe("filterErrors", () => {
  const error = (id: number, kind: string, retryable: boolean): RunError => ({
    id,
    run_id: 41,
    record_ref: `r${id}`,
    message: "boom",
    side: "source",
    kind,
    retryable,
    retried: false,
    payload: null,
  });
  const errors = [error(1, "mapping", false), error(2, "remote", true), error(3, "remote", false)];

  it("filters by kind and retryable flag", () => {
    expect(filterErrors(errors, { kind: "", retryable: "" })).toHaveLength(3);
    expect(filterErrors(errors, { kind: "remote", retryable: "" }).map((e) => e.id)).toEqual([
      2, 3,
    ]);
    expect(filterErrors(errors, { kind: "", retryable: "yes" }).map((e) => e.id)).toEqual([2]);
    expect(filterErrors(errors, { kind: "remote", retryable: "no" }).map((e) => e.id)).toEqual([3]);
  });
});
