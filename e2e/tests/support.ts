import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

export const SUWE_API = process.env.E2E_SUWE_URL ?? "http://localhost:8000";
export const ODOO_PORT = process.env.E2E_ODOO_PORT ?? "8169";
export const ODOO_URL = `http://127.0.0.1:${ODOO_PORT}`;
export const ODOO_DB = "e2e";
export const ODOO_LOGIN = "admin";
export const ODOO_KEY = "e2e-odoo-api-key-0123456789";
export const ADMIN_USER = process.env.E2E_ADMIN_USER ?? "e2e-admin";
export const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-password-1";

const CLIENTS = `${SUWE_API}/api/v1/organization/clients`;

/**
 * The SUWE fake is an external dependency (Docker, :8000). Skip the whole file, loudly, when it
 * is not reachable, like the backend `integration` marker; never fail silently or pass vacuously.
 */
export function requireSuweFake(): void {
  test.beforeAll(async ({ request }) => {
    const reachable = await request
      .get(`${CLIENTS}?page=1&page_size=1`, { timeout: 3_000 })
      .then((r) => r.ok())
      .catch(() => false);
    const reason = `SUWE fake API is not reachable at ${SUWE_API} (start the api_mock container or set E2E_SUWE_URL)`;
    if (!reachable) console.warn(`[e2e] SKIPPED: ${reason}`);
    test.skip(!reachable, reason);
  });
}

/** Live number of clients served by the fake; assertions never hard-code it. */
export async function suweClientCount(request: APIRequestContext): Promise<number> {
  const response = await request.get(`${CLIENTS}?page=1&page_size=1`);
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { total: number };
  return body.total;
}

/** Every client uuid served by the fake (walks all pages). */
export async function suweClientIds(request: APIRequestContext): Promise<string[]> {
  const ids: string[] = [];
  for (let page = 1; ; page += 1) {
    const response = await request.get(`${CLIENTS}?page=${page}&page_size=50`);
    expect(response.ok()).toBe(true);
    const body = (await response.json()) as { items: Array<{ uuid: string }>; total_pages: number };
    ids.push(...body.items.map((item) => item.uuid));
    if (page >= body.total_pages) return ids;
  }
}

/** Calls the fake Odoo JSON-RPC like the connector does (read-only helper for assertions). */
export async function odooCall<T>(
  request: APIRequestContext,
  model: string,
  method: string,
  args: unknown[],
  kwargs: Record<string, unknown> = {},
): Promise<T> {
  const response = await request.post(`${ODOO_URL}/jsonrpc`, {
    data: {
      jsonrpc: "2.0",
      method: "call",
      params: {
        service: "object",
        method: "execute_kw",
        args: [ODOO_DB, 2, ODOO_KEY, model, method, args, kwargs],
      },
      id: 1,
    },
  });
  const body = (await response.json()) as { result: T; error?: unknown };
  expect(body.error).toBeUndefined();
  return body.result;
}

export async function login(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Usuario").fill(username);
  await page.getByLabel("Contraseña").fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
}

/** Logs in and waits for the app shell, so a following navigation cannot cancel the request. */
export async function signIn(page: Page, username: string, password: string): Promise<void> {
  await login(page, username, password);
  await expect(page.getByRole("navigation", { name: "Navegación principal" })).toBeVisible();
}

export async function logout(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await expect(page.getByRole("heading", { name: "Iniciar sesión" })).toBeVisible();
}
