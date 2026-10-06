import { api } from "@/api/client";
import type { Job, JobInput, TriggerRunRequest } from "@/features/jobs/types";
import type { Run } from "@/features/runs/types";

export const JOBS_KEY = ["jobs"] as const;
export const jobKey = (id: number) => [...JOBS_KEY, id] as const;

export const listJobs = async (): Promise<Job[]> =>
  (await api.get<{ items: Job[] }>("/jobs")).items;

export const getJob = (id: number) => api.get<Job>(`/jobs/${id}`);

export const createJob = (input: JobInput) => api.post<Job>("/jobs", input);

export const updateJob = (id: number, input: JobInput) => api.put<Job>(`/jobs/${id}`, input);

export const deleteJob = (id: number) => api.delete<void>(`/jobs/${id}`);

/** Answers 202 with the queued run; the work continues in the background. */
export const triggerRun = ({ jobId, dryRun }: TriggerRunRequest) =>
  api.post<Run>(`/jobs/${jobId}/runs`, { dry_run: dryRun });
