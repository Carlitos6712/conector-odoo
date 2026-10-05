import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { csrfStore } from "@/api/client";
import { JOBS_KEY } from "@/features/jobs/api";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import {
  useDeleteJob,
  useJobs,
  useSaveJob,
  useSetJobEnabled,
  useTriggerRun,
} from "@/features/jobs/hooks";
import { jobToInput } from "@/features/jobs/form";
import { RUNS_KEY } from "@/features/runs/api";
import { useLastRuns, useRun } from "@/features/runs/hooks";
import { json, stubApi } from "@/test/utils";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

const body = (mock: ReturnType<typeof stubApi>, call = 0) =>
  JSON.parse(String((mock.mock.calls[call]?.[1] as RequestInit).body));

beforeEach(() => csrfStore.set("csrf-1"));
afterEach(() => vi.unstubAllGlobals());

describe("jobs hooks", () => {
  it("lists jobs", async () => {
    stubApi({ "GET /jobs": () => json({ items: [jobFixture()] }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useJobs(), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(result.current.data?.[0]?.name).toBe("Clientes a Odoo");
  });

  it("creates a job and invalidates the list", async () => {
    const mock = stubApi({ "POST /jobs": () => json(jobFixture(), 201) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useSaveJob(), { wrapper });
    const input = jobToInput(jobFixture());
    const saved = await act(() => result.current.mutateAsync({ input }));
    expect(saved.id).toBe(7);
    expect(body(mock)).toEqual(input);
    expect(spy).toHaveBeenCalledWith({ queryKey: JOBS_KEY });
  });

  it("updates an existing job with PUT", async () => {
    const mock = stubApi({ "PUT /jobs/7": () => json(jobFixture({ name: "Otro" })) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSaveJob(), { wrapper });
    const input = { ...jobToInput(jobFixture()), name: "Otro" };
    await act(() => result.current.mutateAsync({ id: 7, input }));
    expect(mock).toHaveBeenCalledWith(
      "/admin/api/jobs/7",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(body(mock).name).toBe("Otro");
  });

  it("deletes a job and invalidates the list", async () => {
    stubApi({ "DELETE /jobs/7": () => new Response(null, { status: 204 }) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDeleteJob(), { wrapper });
    await act(() => result.current.mutateAsync(7));
    expect(spy).toHaveBeenCalledWith({ queryKey: JOBS_KEY });
  });

  it("toggles a job by sending the whole definition with the new flag", async () => {
    const job = jobFixture({
      trigger: { kind: "schedule", cron: "0 9 * * *" },
      next_fire: "2026-03-02T09:00:00Z",
    });
    const mock = stubApi({ "PUT /jobs/7": () => json({ ...job, enabled: false }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSetJobEnabled(), { wrapper });
    await act(() => result.current.mutateAsync({ job, enabled: false }));
    expect(body(mock)).toEqual({ ...jobToInput(job), enabled: false });
  });

  it("starts a run and refreshes the run history", async () => {
    const mock = stubApi({
      "POST /jobs/7/runs": () => json(runFixture({ status: "queued", dry_run: true }), 202),
    });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useTriggerRun(), { wrapper });
    const run = await act(() => result.current.mutateAsync({ jobId: 7, dryRun: true }));
    expect(run.status).toBe("queued");
    expect(body(mock)).toEqual({ dry_run: true });
    expect(spy).toHaveBeenCalledWith({ queryKey: RUNS_KEY });
  });
});

describe("runs hooks", () => {
  it("reads the recent runs and indexes the last one of each job", async () => {
    const mock = stubApi({
      "GET /runs?limit=200": () =>
        json({
          items: [
            runFixture({ id: 5, job_id: 7, started_at: "2026-03-02T10:00:00Z" }),
            runFixture({ id: 4, job_id: 7, started_at: "2026-03-01T10:00:00Z" }),
          ],
        }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useLastRuns(), { wrapper });
    await waitFor(() => expect(result.current.data?.get(7)?.id).toBe(5));
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("fetches one run", async () => {
    stubApi({
      "GET /runs/41": () => json({ ...runFixture(), options: {}, checkpoint: {}, sample: [] }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useRun(41), { wrapper });
    await waitFor(() => expect(result.current.data?.id).toBe(41));
  });

  it("does not fetch without an id", () => {
    const mock = stubApi({});
    const { wrapper } = setup();
    renderHook(() => useRun(null), { wrapper });
    expect(mock).not.toHaveBeenCalled();
  });
});
