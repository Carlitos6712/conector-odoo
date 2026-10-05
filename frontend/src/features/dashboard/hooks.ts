import { useQuery } from "@tanstack/react-query";
import { DASHBOARD_KEY, getDashboard } from "@/features/dashboard/api";
import { dashboardRefetchInterval } from "@/features/dashboard/derive";
import { listRecentRuns, RUNS_KEY } from "@/features/runs/api";

/** The summary; refreshes itself while a visible run is queued or running. */
export const useDashboard = () =>
  useQuery({
    queryKey: DASHBOARD_KEY,
    queryFn: getDashboard,
    refetchInterval: (query) => dashboardRefetchInterval(query.state.data, document.hidden),
  });

/**
 * The 200 latest runs (newest first) for the outcome chart and the repeated-failure check.
 * Shares its cache entry with `useLastRuns`; the caller passes the page's polling interval.
 */
export const useRecentRuns = (refetchInterval: number | false) =>
  useQuery({
    queryKey: [...RUNS_KEY, "recent"],
    queryFn: () => listRecentRuns(),
    refetchInterval,
  });
