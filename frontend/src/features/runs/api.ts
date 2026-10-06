import { api } from "@/api/client";
import type { Run, RunDetail, RunErrorPage, RunFilters, RunListPage } from "@/features/runs/types";

export const RUNS_KEY = ["runs"] as const;
export const runKey = (id: number) => [...RUNS_KEY, id] as const;

export const RUNS_PAGE_SIZE = 25;
export const ERRORS_PAGE_SIZE = 20;

/** The 200 most recent runs, newest first: enough to find each job's last run. */
export const listRecentRuns = async (limit = 200): Promise<Run[]> =>
  (await api.get<{ items: Run[] }>(`/runs?limit=${limit}`)).items;

/**
 * `GET /runs` has no total, so a page asks for one extra row: if it comes back, a next page
 * exists. Pages are 1-based.
 */
export function runsQuery(filters: RunFilters, page: number): string {
  const params = new URLSearchParams();
  if (filters.jobId != null) params.set("job_id", String(filters.jobId));
  if (filters.status) params.set("status", filters.status);
  params.set("limit", String(RUNS_PAGE_SIZE + 1));
  if (page > 1) params.set("offset", String((page - 1) * RUNS_PAGE_SIZE));
  return `/runs?${params.toString()}`;
}

export async function listRuns(filters: RunFilters, page: number): Promise<RunListPage> {
  const { items } = await api.get<{ items: Run[] }>(runsQuery(filters, page));
  return { items: items.slice(0, RUNS_PAGE_SIZE), hasNext: items.length > RUNS_PAGE_SIZE };
}

export const getRun = (id: number) => api.get<RunDetail>(`/runs/${id}`);

export interface ErrorPageQuery {
  page: number;
  onlyUnretried: boolean;
}

export function errorsQuery(id: number, limit: number, query: ErrorPageQuery): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.page > 1) params.set("offset", String((query.page - 1) * limit));
  if (query.onlyUnretried) params.set("only_unretried", "true");
  return `/runs/${id}/errors?${params.toString()}`;
}

export const listRunErrorPage = (id: number, query: ErrorPageQuery, limit = ERRORS_PAGE_SIZE) =>
  api.get<RunErrorPage>(errorsQuery(id, limit, query));

/** The first few errors, for summaries; the full list belongs to the run page. */
export const listRunErrors = (id: number, limit: number) =>
  listRunErrorPage(id, { page: 1, onlyUnretried: false }, limit);

export type RunActionName = "cancel" | "resume" | "retryFailed";

const ACTION_PATH: Record<RunActionName, string> = {
  cancel: "cancel",
  resume: "resume",
  retryFailed: "retry-failed",
};

/** Cancel answers 200 with the run; resume and retry answer 202 with the (new) run. */
export const runAction = (id: number, action: RunActionName) =>
  api.post<Run>(`/runs/${id}/${ACTION_PATH[action]}`);
