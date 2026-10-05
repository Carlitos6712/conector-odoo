import { useQuery } from "@tanstack/react-query";
import { getRun, listRecentRuns, listRunErrors, runKey, RUNS_KEY } from "@/features/runs/api";
import { latestRunByJob, runRefetchInterval } from "@/features/runs/summary";

/** Last real run of every job, from one request. */
export const useLastRuns = () =>
  useQuery({
    queryKey: [...RUNS_KEY, "recent"],
    queryFn: () => listRecentRuns(),
    select: latestRunByJob,
  });

/** One run; keeps refreshing while it is queued or running. */
export const useRun = (id: number | null) =>
  useQuery({
    queryKey: runKey(id ?? -1),
    queryFn: () => getRun(id ?? -1),
    enabled: id !== null,
    refetchInterval: (query) => runRefetchInterval(query.state.data),
  });

/** The first few errors of a run, for summaries; the full list belongs to the run page. */
export const useRunErrors = (id: number | null, enabled: boolean, limit = 5) =>
  useQuery({
    queryKey: [...runKey(id ?? -1), "errors", limit],
    queryFn: () => listRunErrors(id ?? -1, limit),
    enabled: enabled && id !== null,
  });
