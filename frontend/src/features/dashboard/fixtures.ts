import type { Dashboard } from "@/features/dashboard/types";

/** Test fixture shared by the dashboard suites (never imported by app code). */
export function dashboardFixture(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    profiles: 2,
    mappings: 3,
    jobs_total: 4,
    jobs_enabled: 3,
    runs_last_24h: { queued: 0, running: 0, succeeded: 5, partial: 1, failed: 2, cancelled: 0 },
    active_runs: [],
    recent_runs: [],
    recent_failures: [],
    scheduled: [],
    ...overrides,
  };
}
