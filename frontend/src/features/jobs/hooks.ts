import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createJob,
  deleteJob,
  getJob,
  jobKey,
  JOBS_KEY,
  listJobs,
  triggerRun,
  updateJob,
} from "@/features/jobs/api";
import { jobToInput } from "@/features/jobs/form";
import type { Job, JobInput } from "@/features/jobs/types";
import { RUNS_KEY } from "@/features/runs/api";

export const useJobs = () => useQuery({ queryKey: JOBS_KEY, queryFn: listJobs });

export const useJob = (id: number | null) =>
  useQuery({
    queryKey: jobKey(id ?? -1),
    queryFn: () => getJob(id ?? -1),
    enabled: id !== null,
  });

/** Create (no `id`) or update. Saving also changes the schedule, so cached jobs are dropped. */
export function useSaveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id?: number; input: JobInput }) =>
      id === undefined ? createJob(input) : updateJob(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: JOBS_KEY }),
  });
}

export function useDeleteJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: JOBS_KEY }),
  });
}

/** PUT replaces the whole job, so the toggle sends the stored definition with the new flag. */
export function useSetJobEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ job, enabled }: { job: Job; enabled: boolean }) =>
      updateJob(job.id, { ...jobToInput(job), enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: JOBS_KEY }),
  });
}

/** Starts a (dry) run; the history and the "last run" column are refreshed. */
export function useTriggerRun() {
  const queryClient = useQueryClient();
  return useMutation({
    gcTime: 0,
    mutationFn: triggerRun,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RUNS_KEY }),
  });
}
