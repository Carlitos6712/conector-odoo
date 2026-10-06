/** Typed fetch wrapper for `/admin/api`: cookie session, CSRF header and error envelope parsing. */

export const API_BASE = "/admin/api";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

/** An error answered by the API (`{error, detail}`) or raised by the transport (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly retryAfterSeconds: number | null;
  /** Extra envelope fields, e.g. `issues` on 422 validation errors. */
  readonly extra: Record<string, unknown>;

  constructor(init: {
    status: number;
    code: string;
    detail: string;
    retryAfterSeconds?: number | null;
    extra?: Record<string, unknown>;
  }) {
    super(init.detail || init.code);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.detail = init.detail;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
    this.extra = init.extra ?? {};
  }
}

/** CSRF token kept in memory only: never persisted, so it dies with the tab. */
let csrfToken: string | null = null;
export const csrfStore = {
  get: (): string | null => csrfToken,
  set: (token: string): void => {
    csrfToken = token;
  },
  clear: (): void => {
    csrfToken = null;
  },
};

let unauthorizedHandler: (() => void) | null = null;

/** Registers the callback run when a protected call answers 401 (session expired). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
  /** Set to false for calls where 401 is an expected answer (login). */
  handleUnauthorized?: boolean;
}

async function toApiError(response: Response): Promise<ApiError> {
  const retryAfter = Number(response.headers.get("Retry-After"));
  const retryAfterSeconds = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null;
  try {
    const payload: unknown = await response.json();
    if (payload && typeof payload === "object" && "error" in payload) {
      const { error, detail, ...extra } = payload as Record<string, unknown>;
      return new ApiError({
        status: response.status,
        code: String(error),
        detail: typeof detail === "string" ? detail : "",
        retryAfterSeconds,
        extra,
      });
    }
  } catch {
    // Not JSON (proxy error page, empty body): fall through to the generic error.
  }
  return new ApiError({
    status: response.status,
    code: "http_error",
    detail: response.statusText,
    retryAfterSeconds,
  });
}

export async function apiRequest<T = unknown>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  let body: string | undefined;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  const token = csrfStore.get();
  if (method !== "GET" && token) headers.set("X-CSRF-Token", token);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body,
      credentials: "include",
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError({ status: 0, code: "network_error", detail: "" });
  }

  if (!response.ok) {
    const error = await toApiError(response);
    if (response.status === 401 && options.handleUnauthorized !== false) {
      csrfStore.clear();
      unauthorizedHandler?.();
    }
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => apiRequest<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    apiRequest<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, options?: RequestOptions) => apiRequest<T>("DELETE", path, options),
};
