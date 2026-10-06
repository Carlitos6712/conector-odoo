import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { csrfStore } from "@/api/client";
import { MAPPINGS_KEY } from "@/features/mappings/api";
import {
  dryRunFixture,
  mappingDocFixture,
  storedMappingFixture,
} from "@/features/mappings/fixtures";
import {
  useDeleteMapping,
  useDryRun,
  useMappings,
  useSaveMapping,
  useSuggest,
} from "@/features/mappings/hooks";
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

describe("mappings hooks", () => {
  it("lists the latest version of every mapping", async () => {
    stubApi({ "GET /mappings": () => json({ items: [storedMappingFixture()] }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useMappings(), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(result.current.data?.[0]?.name).toBe("clients-to-partner");
  });

  it("saves with the profile ids and invalidates the mappings", async () => {
    const mock = stubApi({
      "PUT /mappings/clients-to-partner": () =>
        json({ mapping: storedMappingFixture({ version: 4 }), created: true, warnings: [] }),
    });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useSaveMapping(), { wrapper });
    const saved = await act(() =>
      result.current.mutateAsync({
        name: "clients-to-partner",
        definition: mappingDocFixture(),
        sourceProfileId: 1,
        targetProfileId: 2,
      }),
    );
    expect(saved.mapping.version).toBe(4);
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      definition: mappingDocFixture(),
      source_profile_id: 1,
      target_profile_id: 2,
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: MAPPINGS_KEY });
  });

  it("omits the profile ids when none are chosen", async () => {
    const mock = stubApi({
      "PUT /mappings/clients-to-partner": () =>
        json({ mapping: storedMappingFixture(), created: false, warnings: [] }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSaveMapping(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ name: "clients-to-partner", definition: mappingDocFixture() }),
    );
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ definition: mappingDocFixture() });
  });

  it("invalidates the mappings after a delete", async () => {
    stubApi({ "DELETE /mappings/clients-to-partner": () => new Response(null, { status: 204 }) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDeleteMapping(), { wrapper });
    await act(() => result.current.mutateAsync("clients-to-partner"));
    expect(spy).toHaveBeenCalledWith({ queryKey: MAPPINGS_KEY });
  });

  it("joins dry-run output with the source records by id", async () => {
    stubApi({
      "POST /mappings/dry-run": () => json(dryRunFixture),
      "POST /profiles/1/resources/clients/preview?limit=5": () =>
        json({
          records: [{ id: "u-1", fields: { name: "Acme" } }],
          schema: { name: "clients", label: "", id_field: "id", fields: [] },
        }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useDryRun(), { wrapper });
    const run = await act(() =>
      result.current.mutateAsync({
        definition: mappingDocFixture(),
        sourceProfileId: 1,
        targetProfileId: 2,
        limit: 5,
      }),
    );
    expect(run.report.total).toBe(2);
    expect(run.inputs).toEqual({ "u-1": { name: "Acme" } });
  });

  it("still returns the report when the input preview fails", async () => {
    stubApi({
      "POST /mappings/dry-run": () => json(dryRunFixture),
      "POST /profiles/1/resources/clients/preview?limit=5": () =>
        json({ error: "remote_unavailable", detail: "down" }, 502),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useDryRun(), { wrapper });
    const run = await act(() =>
      result.current.mutateAsync({
        definition: mappingDocFixture(),
        sourceProfileId: 1,
        targetProfileId: 2,
        limit: 5,
      }),
    );
    expect(run.inputs).toEqual({});
  });

  it("asks for suggestions without storing anything", async () => {
    const mock = stubApi({
      "POST /mappings/suggest": () =>
        json({ definition: mappingDocFixture(), unmatched_source: ["a"], unmatched_target: ["b"] }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSuggest(), { wrapper });
    const suggestion = await act(() =>
      result.current.mutateAsync({
        sourceProfileId: 1,
        sourceResource: "clients",
        targetProfileId: 2,
        targetResource: "res.partner",
      }),
    );
    expect(suggestion.unmatched_target).toEqual(["b"]);
    const init = mock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      source_profile_id: 1,
      source_resource: "clients",
      target_profile_id: 2,
      target_resource: "res.partner",
    });
  });
});
