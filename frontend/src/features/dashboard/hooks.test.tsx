import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { dashboardFixture } from "@/features/dashboard/fixtures";
import { useDashboard, useRecentRuns } from "@/features/dashboard/hooks";
import { runFixture } from "@/features/jobs/fixtures";
import { json, stubApi } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("dashboard hooks", () => {
  it("loads the summary", async () => {
    stubApi({ "GET /dashboard": () => json(dashboardFixture({ profiles: 4 })) });
    const { result } = renderHook(() => useDashboard(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.profiles).toBe(4);
  });

  it("loads the latest runs", async () => {
    const mock = stubApi({ "GET /runs?limit=200": () => json({ items: [runFixture({ id: 3 })] }) });
    const { result } = renderHook(() => useRecentRuns(false), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0]?.id).toBe(3);
    expect(mock).toHaveBeenCalledTimes(1);
  });
});
