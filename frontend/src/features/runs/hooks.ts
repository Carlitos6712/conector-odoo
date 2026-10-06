import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRun,
  listRecentRuns,
  listRunErrorPage,
  listRunErrors,
  listRuns,
  runAction,
  runKey,
  RUNS_KEY,
  type ErrorPageQuery,
  type RunActionName,
} from "@/features/runs/api";
import { listRefetchInterval } from "@/features/runs/policy";
import { latestRunByJob, runRefetchInterval } from "@/features/runs/summary";
import type { RunFilters } from "@/features/runs/types";

/** Last real run of every job, from one request. */
export const useLastRuns = () =>
  useQuery({
    queryKey: [...RUNS_KEY, "recent"],
    queryFn: () => listRecentRuns(),
    select: latestRunByJob,
  });

/** One page of the history; refreshes itself while a visible run is queued or running. */
export const useRuns = (filters: RunFilters, page: number) =>
  useQuery({
    queryKey: [...RUNS_KEY, "list", filters.jobId ?? null, filters.status ?? null, page],
    queryFn: () => listRuns(filters, page),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => listRefetchInterval(query.state.data?.items, document.hidden),
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

/** A page of the errors of a run; refreshed by the page while the run is active. */
export const useRunErrorPage = (
  id: number | null,
  query: ErrorPageQuery,
  enabled: boolean,
  refetchInterval: number | false = false,
) =>
  useQuery({
    queryKey: [...runKey(id ?? -1), "error-page", query.page, query.onlyUnretried],
    queryFn: () => listRunErrorPage(id ?? -1, query),
    enabled: enabled && id !== null,
    placeholderData: keepPreviousData,
    refetchInterval,
  });

/** Cancel, resume or retry-failed; every run query (list, detail, errors) is refreshed after. */
export function useRunAction() {
  const queryClient = useQueryClient();
  return useMutation({
    gcTime: 0,
    mutationFn: ({ id, action }: { id: number; action: RunActionName }) => runAction(id, action),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RUNS_KEY }),
  });
}
