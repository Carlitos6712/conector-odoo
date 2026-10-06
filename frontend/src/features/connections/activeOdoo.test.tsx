import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { ApiError, csrfStore } from "@/api/client";
import { DASHBOARD_KEY } from "@/features/dashboard/api";
import { ACTIVE_ODOO_KEY, PROFILES_KEY } from "@/features/connections/api";
import { describeActiveOdooError } from "@/features/connections/errors";
import {
  activationFailure,
  activeOdooFixture,
  noOdooFixture,
} from "@/features/connections/fixtures";
import { useActivateOdoo, useActiveOdoo, useDisconnectOdoo } from "@/features/connections/hooks";
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

describe("active Odoo hooks", () => {
  it("reads the active connection under the ['odoo','active'] key", async () => {
    stubApi({ "GET /odoo/active": () => json(activeOdooFixture()) });
    const { queryClient, wrapper } = setup();
    const { result } = renderHook(() => useActiveOdoo(), { wrapper });
    await waitFor(() => expect(result.current.data?.profile_name).toBe("Odoo producción"));
    expect(queryClient.getQueryData(ACTIVE_ODOO_KEY)).toBeDefined();
    expect(ACTIVE_ODOO_KEY).toEqual(["odoo", "active"]);
  });

  it("activation PUTs the profile id and invalidates active, profiles and dashboard", async () => {
    const fetchMock = stubApi({ "PUT /odoo/active": () => json(activeOdooFixture()) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useActivateOdoo(), { wrapper });
    await act(() => result.current.mutateAsync(2));
    const call = fetchMock.mock.calls[0];
    expect(call?.[1]?.method).toBe("PUT");
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ profile_id: 2 });
    const keys = spy.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toEqual(expect.arrayContaining([ACTIVE_ODOO_KEY, PROFILES_KEY, DASHBOARD_KEY]));
  });

  it("disconnect DELETEs the active connection and invalidates the same caches", async () => {
    const fetchMock = stubApi({ "DELETE /odoo/active": () => json(noOdooFixture) });
    const { queryClient, wrapper } = setup();
    const spy = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useDisconnectOdoo(), { wrapper });
    await act(() => result.current.mutateAsync());
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
    const keys = spy.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toEqual(expect.arrayContaining([ACTIVE_ODOO_KEY, PROFILES_KEY, DASHBOARD_KEY]));
  });
});

const err = (status: number, code: string, extra: Record<string, unknown> = {}) =>
  new ApiError({ status, code, detail: "", extra });

describe("describeActiveOdooError", () => {
  it("carries the probe steps of a failed activation", () => {
    const described = describeActiveOdooError(
      err(422, "odoo_activation_failed", {
        failed_step: activationFailure.failed_step,
        steps: activationFailure.steps,
      }),
    );
    expect(described.messageKey).toBe("connections.active.errors.activationFailed");
    expect(described.result?.failed_step).toBe("auth");
    expect(described.result?.steps).toHaveLength(4);
  });

  it("ignores malformed step payloads", () => {
    const described = describeActiveOdooError(
      err(422, "odoo_activation_failed", { failed_step: "auth", steps: "nope" }),
    );
    expect(described.result).toBeNull();
    expect(described.messageKey).toBe("connections.active.errors.activationFailed");
  });

  it.each([
    [404, "not_found", "connections.errors.notFound"],
    [403, "forbidden", "connections.errors.forbidden"],
    [409, "conflict", "connections.active.errors.conflict"],
    [422, "validation_error", "connections.active.errors.notOdoo"],
    [503, "vault_not_configured", "connections.errors.vaultMissing"],
    [500, "internal_error", "common.unexpectedError"],
  ])("maps %i %s to %s", (status, code, key) => {
    expect(describeActiveOdooError(err(status, code)).messageKey).toBe(key);
  });

  it("maps transport failures", () => {
    expect(
      describeActiveOdooError(new ApiError({ status: 0, code: "network_error", detail: "" })),
    ).toMatchObject({ messageKey: "common.networkError", result: null });
    expect(describeActiveOdooError(new Error("x")).messageKey).toBe("common.unexpectedError");
  });
});
