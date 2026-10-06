import { ApiError, apiRequest, csrfStore, setUnauthorizedHandler } from "@/api/client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function lastCall(fetchMock: ReturnType<typeof vi.fn>): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, init };
}

describe("apiRequest", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    csrfStore.clear();
    setUnauthorizedHandler(null);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("sends cookies and prefixes the admin api path", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await expect(apiRequest("GET", "/jobs")).resolves.toEqual({ ok: true });
    const { url, init } = lastCall(fetchMock);
    expect(url).toBe("/admin/api/jobs");
    expect(init.credentials).toBe("include");
  });

  it("does not send the CSRF token on GET", async () => {
    csrfStore.set("tok");
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("GET", "/jobs");
    expect(new Headers(lastCall(fetchMock).init.headers).has("X-CSRF-Token")).toBe(false);
  });

  it.each(["POST", "PUT", "PATCH", "DELETE"] as const)("sends the CSRF token on %s", async (m) => {
    csrfStore.set("tok-123");
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest(m, "/jobs", { body: { a: 1 } });
    const { init } = lastCall(fetchMock);
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("tok-123");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
  });

  it("returns undefined for 204 responses", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiRequest("POST", "/auth/logout")).resolves.toBeUndefined();
  });

  it("parses the error envelope into an ApiError", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "not_found", detail: "no such job" }, 404));
    const error = await apiRequest("GET", "/jobs/9").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: "not_found", detail: "no such job" });
  });

  it("keeps extra envelope fields such as issues and Retry-After", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ error: "rate_limited", detail: "slow down" }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "30" },
      }),
    );
    const error = (await apiRequest("POST", "/auth/login").catch((e: unknown) => e)) as ApiError;
    expect(error.retryAfterSeconds).toBe(30);
  });

  it("falls back to a generic error when the body is not the envelope", async () => {
    fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = (await apiRequest("GET", "/jobs").catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 502, code: "http_error" });
  });

  it("wraps network failures", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = (await apiRequest("GET", "/jobs").catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 0, code: "network_error" });
  });

  it("clears the CSRF token and notifies the handler on 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    csrfStore.set("tok");
    fetchMock.mockResolvedValue(jsonResponse({ error: "unauthorized", detail: "expired" }, 401));
    await expect(apiRequest("GET", "/jobs")).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(csrfStore.get()).toBeNull();
  });

  it("does not trigger the 401 handler for credential checks", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    fetchMock.mockResolvedValue(jsonResponse({ error: "invalid_credentials", detail: "x" }, 401));
    await expect(
      apiRequest("POST", "/auth/login", { body: {}, handleUnauthorized: false }),
    ).rejects.toMatchObject({ status: 401 });
    expect(handler).not.toHaveBeenCalled();
  });
});
