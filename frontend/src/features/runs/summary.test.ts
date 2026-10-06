import { runFixture } from "@/features/jobs/fixtures";
import { isActiveStatus, latestRunByJob, runRefetchInterval } from "@/features/runs/summary";

describe("run summaries", () => {
  it("knows which statuses are still moving", () => {
    expect(isActiveStatus("queued")).toBe(true);
    expect(isActiveStatus("running")).toBe(true);
    for (const done of ["succeeded", "partial", "failed", "cancelled"] as const) {
      expect(isActiveStatus(done)).toBe(false);
    }
  });

  it("keeps the most recently started real run of every job", () => {
    const runs = [
      runFixture({ id: 1, job_id: 7, started_at: "2026-03-01T10:00:00Z" }),
      runFixture({ id: 3, job_id: 7, started_at: "2026-03-03T10:00:00Z", status: "failed" }),
      runFixture({ id: 2, job_id: 7, started_at: "2026-03-02T10:00:00Z" }),
      runFixture({ id: 4, job_id: 8, started_at: "2026-03-01T09:00:00Z" }),
    ];
    const latest = latestRunByJob(runs);
    expect(latest.get(7)?.id).toBe(3);
    expect(latest.get(8)?.id).toBe(4);
    expect(latest.size).toBe(2);
  });

  it("ignores dry runs when summarising the last run", () => {
    const runs = [
      runFixture({ id: 1, job_id: 7, started_at: "2026-03-01T10:00:00Z" }),
      runFixture({ id: 2, job_id: 7, started_at: "2026-03-05T10:00:00Z", dry_run: true }),
    ];
    expect(latestRunByJob(runs).get(7)?.id).toBe(1);
  });

  it("polls while a run is active and stops once it finishes", () => {
    expect(runRefetchInterval(undefined)).toBe(false);
    expect(runRefetchInterval(runFixture({ status: "running" }))).toBe(1000);
    expect(runRefetchInterval(runFixture({ status: "queued" }))).toBe(1000);
    expect(runRefetchInterval(runFixture({ status: "succeeded" }))).toBe(false);
  });
});
