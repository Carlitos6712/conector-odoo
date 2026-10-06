import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { csrfStore } from "@/api/client";
import { SESSION_KEY } from "@/auth/api";
import { USERS_KEY } from "@/features/settings/api";
import {
  useChangePassword,
  useCreateUser,
  useDeleteUser,
  useUpdateUser,
  useUsers,
} from "@/features/settings/hooks";
import { json, sessionBody, stubApi } from "@/test/utils";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

const user = (id: number, username: string, role: "admin" | "operator" = "operator") => ({
  id,
  username,
  role,
  created_at: "2026-01-01T00:00:00Z",
});
const body = (mock: ReturnType<typeof stubApi>, call = 0) =>
  JSON.parse(String((mock.mock.calls[call]?.[1] as RequestInit).body));

beforeEach(() => csrfStore.set("csrf-1"));
afterEach(() => vi.unstubAllGlobals());

describe("settings hooks", () => {
  it("lists users", async () => {
    stubApi({ "GET /users": () => json({ items: [user(1, "ana", "admin"), user(2, "bea")] }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useUsers(), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(2));
  });

  it("creates a user and refreshes the list", async () => {
    const mock = stubApi({ "POST /users": () => json(user(3, "cris"), 201) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useCreateUser(), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        username: "cris",
        password: "long-enough-pass",
        role: "operator",
      }),
    );
    expect(body(mock)).toEqual({
      username: "cris",
      password: "long-enough-pass",
      role: "operator",
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: USERS_KEY });
  });

  it("changes a role and resets a password with PATCH", async () => {
    const mock = stubApi({ "PATCH /users/2": () => json(user(2, "bea", "admin")) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useUpdateUser(), { wrapper });
    await act(() => result.current.mutateAsync({ id: 2, patch: { role: "admin" } }));
    await act(() =>
      result.current.mutateAsync({ id: 2, patch: { password: "another-long-pass" } }),
    );
    expect(body(mock, 0)).toEqual({ role: "admin" });
    expect(body(mock, 1)).toEqual({ password: "another-long-pass" });
    expect((mock.mock.calls[0]?.[1] as RequestInit).method).toBe("PATCH");
  });

  it("deletes a user", async () => {
    const mock = stubApi({ "DELETE /users/2": () => new Response(null, { status: 204 }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useDeleteUser(), { wrapper });
    await act(() => result.current.mutateAsync(2));
    expect(mock).toHaveBeenCalledWith("/admin/api/users/2", expect.anything());
  });

  it("changes the own password, adopting the rotated session and CSRF token", async () => {
    const rotated = sessionBody("operator", "csrf-rotated");
    const mock = stubApi({ "POST /auth/password": () => json(rotated) });
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(SESSION_KEY, sessionBody("operator", "csrf-1"));
    const { result } = renderHook(() => useChangePassword(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ current: "old-password-123", next: "new-password-4567" }),
    );
    expect(body(mock)).toEqual({
      current_password: "old-password-123",
      new_password: "new-password-4567",
    });
    expect(csrfStore.get()).toBe("csrf-rotated");
    expect(queryClient.getQueryData(SESSION_KEY)).toEqual(rotated);
  });

  it("keeps the session untouched when the change fails", async () => {
    stubApi({
      "POST /auth/password": () => json({ error: "invalid_current_password", detail: "nope" }, 422),
    });
    const { queryClient, wrapper } = setup();
    const before = sessionBody("operator", "csrf-1");
    queryClient.setQueryData(SESSION_KEY, before);
    const { result } = renderHook(() => useChangePassword(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ current: "x", next: "y" }).catch(() => undefined);
    });
    expect(csrfStore.get()).toBe("csrf-1");
    expect(queryClient.getQueryData(SESSION_KEY)).toEqual(before);
  });
});
