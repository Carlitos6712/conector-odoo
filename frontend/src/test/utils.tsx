import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter } from "react-router-dom";
import { csrfStore, setUnauthorizedHandler } from "@/api/client";
import { createI18n } from "@/i18n";

export type Role = "admin" | "operator";

export function sessionBody(role: Role = "admin", csrf = "csrf-1") {
  return {
    user: { id: 1, username: "ana", role, created_at: "2026-01-01T00:00:00Z" },
    csrf_token: csrf,
    expires_at: "2026-01-02T00:00:00Z",
  };
}

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** Routes a stubbed `fetch` by `"METHOD /path"`; unknown calls fail the test loudly. */
export function stubApi(routes: Record<string, () => Response | Promise<Response>>) {
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url.replace("/admin/api", "")}`;
    const handler = routes[key];
    if (!handler) throw new Error(`unexpected request: ${key}`);
    return handler();
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

export async function renderApp(ui: ReactElement, route = "/") {
  csrfStore.clear();
  setUnauthorizedHandler(null);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const i18n = await createI18n("es");
  return {
    queryClient,
    ...render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>,
    ),
  };
}
