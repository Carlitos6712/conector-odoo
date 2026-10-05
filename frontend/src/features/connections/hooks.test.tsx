import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { csrfStore } from "@/api/client";
import { PROFILES_KEY } from "@/features/connections/api";
import { passingTest, profileFixture } from "@/features/connections/fixtures";
import {
  useCreateProfile,
  useDeleteProfile,
  useProfiles,
  useTestDraft,
  useUpdateProfile,
} from "@/features/connections/hooks";
import type { ProfileInput } from "@/features/connections/types";
import { json, stubApi } from "@/test/utils";

const input: ProfileInput = {
  name: "SUWE",
  type: "rest",
  base_url: "https://api.suwe.test",
  auth_method: "bearer",
  secrets: { token: "super-secret-token" },
};

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

beforeEach(() => csrfStore.set("csrf-1"));
afterEach(() => vi.unstubAllGlobals());

describe("connections hooks", () => {
  it("lists profiles", async () => {
    stubApi({ "GET /profiles": () => json({ items: [profileFixture()] }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useProfiles(), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(1));
  });

  it("invalidates the list after create, update and delete", async () => {
    stubApi({
      "POST /profiles": () => json(profileFixture(), 201),
      "PUT /profiles/1": () => json(profileFixture()),
      "DELETE /profiles/1": () => new Response(null, { status: 204 }),
    });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const create = renderHook(() => useCreateProfile(), { wrapper });
    const update = renderHook(() => useUpdateProfile(), { wrapper });
    const remove = renderHook(() => useDeleteProfile(), { wrapper });
    await act(() => create.result.current.mutateAsync(input));
    await act(() => update.result.current.mutateAsync({ id: 1, input }));
    await act(() => remove.result.current.mutateAsync(1));
    expect(spy).toHaveBeenCalledTimes(3);
    for (const call of spy.mock.calls) expect(call[0]).toEqual({ queryKey: PROFILES_KEY });
  });

  it("posts the draft to /profiles/test without storing anything in the cache", async () => {
    const fetchMock = stubApi({ "POST /profiles/test": () => json(passingTest) });
    const { queryClient, wrapper } = setup();
    const { result, unmount } = renderHook(() => useTestDraft(), { wrapper });
    await act(() => result.current.mutateAsync(input));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    unmount();
    await waitFor(() => expect(queryClient.getMutationCache().getAll()).toHaveLength(0));
    expect(
      JSON.stringify(
        queryClient
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain("super-secret-token");
  });
});
