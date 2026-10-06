import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { triggerRun } from "@/features/jobs/api";
import type { Job } from "@/features/jobs/types";
import { getRun, RUNS_KEY } from "@/features/runs/api";
import { isActiveStatus } from "@/features/runs/summary";
import type { Run } from "@/features/runs/types";
import {
  createRecord,
  deleteRecord,
  listRecords,
  RECORDS_KEY,
  recordsKey,
  updateRecord,
  type ListParams,
} from "@/features/records/api";
import type { RecordTarget } from "@/features/records/types";

export const useRecords = (params: ListParams | null) =>
  useQuery({
    queryKey: params ? recordsKey(params) : [...RECORDS_KEY, "idle"],
    queryFn: ({ signal }) => listRecords(params as ListParams, signal),
    enabled: params !== null,
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  });

export function useUpdateRecord(target: RecordTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fields }: { id: string | number; fields: Record<string, unknown> }) =>
      updateRecord(target, id, fields),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECORDS_KEY }),
  });
}

export function useDeleteRecord(target: RecordTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string | number) => deleteRecord(target, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECORDS_KEY }),
  });
}

export function useCreateRecord(target: RecordTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fields: Record<string, unknown>) => createRecord(target, fields),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECORDS_KEY }),
  });
}

export interface SyncOutcome {
  job: Job;
  run: Run | null;
  error: unknown;
}

const POLL_MS = 1000;
const MAX_POLLS = 120;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Resolves once none of the runs is queued or running (or after a bounded wait). */
async function untilFinished(ids: readonly number[]): Promise<void> {
  for (let poll = 0; poll < MAX_POLLS; poll += 1) {
    const runs = await Promise.all(ids.map((id) => getRun(id)));
    if (!runs.some((run) => isActiveStatus(run.status))) return;
    await sleep(POLL_MS);
  }
}

/**
 * Starts a real run of each given job. The runs go on in the background, so the records list is
 * refreshed right away and again once every started run has finished.
 */
export function useSyncRecords() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: RECORDS_KEY });
  return useMutation({
    gcTime: 0,
    mutationFn: async (jobs: readonly Job[]): Promise<SyncOutcome[]> => {
      const settled = await Promise.allSettled(
        jobs.map((job) => triggerRun({ jobId: job.id, dryRun: false })),
      );
      return settled.map((result, index) => ({
        job: jobs[index]!,
        run: result.status === "fulfilled" ? result.value : null,
        error: result.status === "rejected" ? result.reason : null,
      }));
    },
    onSuccess: (outcomes) => {
      void queryClient.invalidateQueries({ queryKey: RUNS_KEY });
      void refresh();
      const ids = outcomes.flatMap((o) => (o.run ? [o.run.id] : []));
      if (ids.length > 0)
        void untilFinished(ids)
          .catch(() => undefined)
          .finally(refresh);
    },
  });
}
