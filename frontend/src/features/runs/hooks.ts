import { useQuery } from "@tanstack/react-query";
import { getRun, listRecentRuns, runKey, RUNS_KEY } from "@/features/runs/api";
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
