import { api } from "@/api/client";
import type { Run, RunDetail, RunErrorPage } from "@/features/runs/types";

export const RUNS_KEY = ["runs"] as const;
export const runKey = (id: number) => [...RUNS_KEY, id] as const;

/** The 200 most recent runs, newest first: enough to find each job's last run. */
export const listRecentRuns = async (limit = 200): Promise<Run[]> =>
  (await api.get<{ items: Run[] }>(`/runs?limit=${limit}`)).items;

export const getRun = (id: number) => api.get<RunDetail>(`/runs/${id}`);

export const listRunErrors = (id: number, limit: number) =>
  api.get<RunErrorPage>(`/runs/${id}/errors?limit=${limit}`);
