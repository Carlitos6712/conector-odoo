import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import {
  attentionItems,
  dashboardRefetchInterval,
  nextFireOf,
  runsByDay,
} from "@/features/dashboard/derive";
import { dashboardFixture } from "@/features/dashboard/fixtures";

describe("dashboardRefetchInterval", () => {
  it("polls while a run is active and the tab is visible", () => {
    const data = dashboardFixture({ active_runs: [runFixture({ status: "running" })] });
    expect(dashboardRefetchInterval(data, false)).toBe(3000);
  });

  it("stops when the tab is hidden, nothing is active or there is no data", () => {
    const data = dashboardFixture({ active_runs: [runFixture({ status: "running" })] });
    expect(dashboardRefetchInterval(data, true)).toBe(false);
    expect(dashboardRefetchInterval(dashboardFixture(), false)).toBe(false);
    expect(dashboardRefetchInterval(undefined, false)).toBe(false);
  });
});

// Midday local time keeps every assertion independent of the machine time zone.
const NOW = new Date(2026, 2, 10, 12, 0, 0);
const at = (day: number, hour = 12) => new Date(2026, 2, day, hour, 0, 0).toISOString();

describe("runsByDay", () => {
  it("returns one bucket per day, oldest first, ending today", () => {
    const buckets = runsByDay([], NOW, 7);
    expect(buckets).toHaveLength(7);
    expect(buckets[0]!.day).toBe("2026-03-04");
    expect(buckets[6]!.day).toBe("2026-03-10");
    expect(buckets.every((b) => b.total === 0)).toBe(true);
  });

  it("counts real runs per day by outcome and groups the rest under other", () => {
    const runs = [
      runFixture({ id: 1, status: "succeeded", started_at: at(10) }),
      runFixture({ id: 2, status: "succeeded", started_at: at(10, 8) }),
      runFixture({ id: 3, status: "failed", started_at: at(10, 9) }),
      runFixture({ id: 4, status: "partial", started_at: at(9) }),
      runFixture({ id: 5, status: "cancelled", started_at: at(9, 10) }),
      runFixture({ id: 6, status: "running", started_at: at(9, 11) }),
    ];
    const buckets = runsByDay(runs, NOW, 7);
    const today = buckets[6]!;
    const yesterday = buckets[5]!;
    expect(today).toMatchObject({ succeeded: 2, partial: 0, failed: 1, other: 0, total: 3 });
    expect(yesterday).toMatchObject({ succeeded: 0, partial: 1, failed: 0, other: 2, total: 3 });
  });

  it("ignores dry runs and runs outside the window", () => {
    const runs = [
      runFixture({ id: 1, dry_run: true, started_at: at(10) }),
      runFixture({ id: 2, started_at: at(1) }),
      runFixture({ id: 3, started_at: at(11) }),
    ];
    expect(runsByDay(runs, NOW, 7).every((b) => b.total === 0)).toBe(true);
  });
});

describe("attentionItems", () => {
  const jobs = [jobFixture({ id: 7, name: "Clientes" }), jobFixture({ id: 8, name: "Pedidos" })];

  it("lists recent failures, newest first, as failed-run items", () => {
    const failures = [
      runFixture({ id: 5, status: "failed" }),
      runFixture({ id: 4, status: "partial" }),
    ];
    const items = attentionItems({ failures, active: [], recent: [], jobs, now: NOW.getTime() });
    expect(items.map((i) => i.kind)).toEqual(["failedRun", "failedRun"]);
    expect(items[0]).toMatchObject({ run: { id: 5 } });
  });

  it("flags active runs that have been silent past the stale window", () => {
    const stale = runFixture({
      id: 9,
      status: "running",
      started_at: at(10, 9),
      heartbeat_at: at(10, 9),
    });
    const fresh = runFixture({
      id: 10,
      status: "running",
      started_at: at(10, 11),
      heartbeat_at: new Date(NOW.getTime() - 60_000).toISOString(),
    });
    const items = attentionItems({
      failures: [],
      active: [stale, fresh],
      recent: [],
      jobs,
      now: NOW.getTime(),
    });
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "staleRun", run: { id: 9 } });
  });

  it("flags a job whose last runs failed twice or more in a row", () => {
    const recent = [
      runFixture({ id: 30, job_id: 7, status: "failed", started_at: at(10, 11) }),
      runFixture({ id: 29, job_id: 7, status: "failed", started_at: at(10, 10) }),
      runFixture({ id: 28, job_id: 7, status: "succeeded", started_at: at(10, 9) }),
      runFixture({ id: 27, job_id: 8, status: "failed", started_at: at(10, 8) }),
      runFixture({ id: 26, job_id: 8, status: "succeeded", started_at: at(10, 7) }),
    ];
    const items = attentionItems({ failures: [], active: [], recent, jobs, now: NOW.getTime() });
    expect(items).toEqual([{ kind: "repeatedFailures", jobId: 7, name: "Clientes", count: 2 }]);
  });

  it("ignores dry runs and cancelled runs do not break or extend a streak", () => {
    const recent = [
      runFixture({ id: 4, job_id: 7, status: "failed", started_at: at(10, 11) }),
      runFixture({ id: 3, job_id: 7, status: "failed", dry_run: true, started_at: at(10, 10) }),
      runFixture({ id: 2, job_id: 7, status: "cancelled", started_at: at(10, 9) }),
      runFixture({ id: 1, job_id: 7, status: "failed", started_at: at(10, 8) }),
    ];
    const items = attentionItems({ failures: [], active: [], recent, jobs, now: NOW.getTime() });
    expect(items).toEqual([{ kind: "repeatedFailures", jobId: 7, name: "Clientes", count: 2 }]);
  });

  it("is empty when everything is healthy", () => {
    const recent = [runFixture({ id: 1, status: "succeeded" })];
    expect(attentionItems({ failures: [], active: [], recent, jobs, now: NOW.getTime() })).toEqual(
      [],
    );
  });
});

describe("nextFireOf", () => {
  it("uses the scheduler's next fire when the API has one", () => {
    const next = nextFireOf(
      { job_id: 1, name: "a", cron: "0 * * * *", next_fire: "2026-03-10T13:00:00Z" },
      NOW,
    );
    expect(next).toEqual({ at: "2026-03-10T13:00:00Z", estimated: false });
  });

  it("computes it from the cron when the scheduler reports none", () => {
    const next = nextFireOf({ job_id: 1, name: "a", cron: "0 * * * *", next_fire: null }, NOW);
    expect(next?.estimated).toBe(true);
    expect(Date.parse(next!.at)).toBeGreaterThan(NOW.getTime());
  });

  it("returns null when the cron never fires", () => {
    expect(
      nextFireOf({ job_id: 1, name: "a", cron: "0 0 31 2 *", next_fire: null }, NOW),
    ).toBeNull();
  });
});
