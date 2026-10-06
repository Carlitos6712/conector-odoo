import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { csrfStore } from "@/api/client";
import { runFixture } from "@/features/jobs/fixtures";
import { RUNS_PAGE_SIZE, runsQuery, RUNS_KEY } from "@/features/runs/api";
import { useRunAction, useRunErrorPage, useRuns } from "@/features/runs/hooks";
import { json, stubApi } from "@/test/utils";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

beforeEach(() => csrfStore.set("csrf-1"));
afterEach(() => vi.unstubAllGlobals());

describe("runsQuery", () => {
  it("asks for one extra row to know whether another page exists", () => {
    expect(runsQuery({}, 1)).toBe(`/runs?limit=${RUNS_PAGE_SIZE + 1}`);
  });

  it("sends the server-side filters and the offset of the page", () => {
    expect(runsQuery({ jobId: 7, status: "failed" }, 3)).toBe(
      `/runs?job_id=7&status=failed&limit=${RUNS_PAGE_SIZE + 1}&offset=${RUNS_PAGE_SIZE * 2}`,
    );
  });

  it("omits empty filters", () => {
    expect(runsQuery({ jobId: null, status: null }, 1)).toBe(`/runs?limit=${RUNS_PAGE_SIZE + 1}`);
  });
});

describe("runs hooks", () => {
  it("returns a page of runs and whether there is a next one", async () => {
    const many = Array.from({ length: RUNS_PAGE_SIZE + 1 }, (_, i) => runFixture({ id: i + 1 }));
    stubApi({ [`GET ${runsQuery({}, 1)}`]: () => json({ items: many }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useRuns({}, 1), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.items).toHaveLength(RUNS_PAGE_SIZE);
    expect(result.current.data?.hasNext).toBe(true);
  });

  it("knows the last page", async () => {
    stubApi({ [`GET ${runsQuery({}, 1)}`]: () => json({ items: [runFixture()] }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useRuns({}, 1), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.hasNext).toBe(false);
  });

  it("pages the errors of a run with the server-side pending filter", async () => {
    const mock = stubApi({
      "GET /runs/41/errors?limit=20&offset=20&only_unretried=true": () =>
        json({ items: [], total: 25 }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useRunErrorPage(41, { page: 2, onlyUnretried: true }, true),
      { wrapper },
    );
    await waitFor(() => expect(result.current.data?.total).toBe(25));
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["cancel", "/runs/41/cancel"],
    ["resume", "/runs/41/resume"],
    ["retryFailed", "/runs/41/retry-failed"],
  ] as const)("posts %s and invalidates every run query", async (action, path) => {
    const mock = stubApi({ [`POST ${path}`]: () => json(runFixture({ id: 50 }), 202) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useRunAction(), { wrapper });
    const run = await act(() => result.current.mutateAsync({ id: 41, action }));
    expect(run.id).toBe(50);
    expect(mock).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: RUNS_KEY });
  });
});
