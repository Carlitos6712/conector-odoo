import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { csrfStore } from "@/api/client";
import { RESOURCES_KEY } from "@/features/resources/api";
import { configFixture, previewFixture, storedFixture } from "@/features/resources/fixtures";
import {
  useDeleteResource,
  useImportOpenApi,
  usePreview,
  useResources,
  useSaveResource,
} from "@/features/resources/hooks";
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

describe("resources hooks", () => {
  it("lists the catalog of one profile with its invalid entries", async () => {
    stubApi({
      "GET /profiles/1/resources": () =>
        json({ items: [storedFixture()], invalid: [{ name: "broken", reason: "bad json" }] }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useResources(1), { wrapper });
    await waitFor(() => expect(result.current.data?.items).toHaveLength(1));
    expect(result.current.data?.invalid).toEqual([{ name: "broken", reason: "bad json" }]);
  });

  it("invalidates the catalog after save and delete", async () => {
    stubApi({
      "PUT /profiles/1/resources/clients": () => json(storedFixture()),
      "DELETE /profiles/1/resources/clients": () => new Response(null, { status: 204 }),
    });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const save = renderHook(() => useSaveResource(), { wrapper });
    const remove = renderHook(() => useDeleteResource(), { wrapper });
    await act(() =>
      save.result.current.mutateAsync({
        profileId: 1,
        input: { ...configFixture(), source: "manual" },
      }),
    );
    await act(() => remove.result.current.mutateAsync({ profileId: 1, name: "clients" }));
    expect(spy).toHaveBeenCalledTimes(2);
    for (const call of spy.mock.calls) expect(call[0]).toEqual({ queryKey: RESOURCES_KEY });
  });

  it("posts the preview with the requested limit", async () => {
    const fetchMock = stubApi({
      "POST /profiles/1/resources/clients/preview?limit=3": () => json(previewFixture),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => usePreview(1, "clients", 3), { wrapper });
    await waitFor(() => expect(result.current.data?.records).toHaveLength(2));
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("POST");
  });

  it("imports without invalidating anything (nothing is saved)", async () => {
    stubApi({
      "POST /profiles/1/resources/import": () =>
        json({ candidates: [configFixture()], warnings: ["w"], base_path: "/api" }),
    });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useImportOpenApi(), { wrapper });
    const report = await act(() =>
      result.current.mutateAsync({ profileId: 1, request: { url: "https://x.test/spec.json" } }),
    );
    expect(report.candidates).toHaveLength(1);
    expect(spy).not.toHaveBeenCalled();
  });
});
