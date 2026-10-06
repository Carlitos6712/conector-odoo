import type { ConnectionTestResult, Profile } from "@/features/connections/types";

/** Test fixtures shared by the connections suites (never imported by app code). */
export function profileFixture(overrides: Partial<Profile> = {}): Profile {
  return {
    id: 1,
    name: "SUWE",
    type: "rest",
    base_url: "https://api.suwe.test/v1",
    auth_method: "bearer",
    extra_headers: {},
    tls_verify: true,
    timeout_seconds: 30,
    odoo_db: null,
    odoo_login: null,
    token_url: null,
    scope: null,
    api_key_header: "X-API-Key",
    has_secret: { token: true },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export const odooProfileFixture = profileFixture({
  id: 2,
  name: "Odoo producción",
  type: "odoo",
  base_url: "https://odoo.example.com",
  auth_method: "api_key",
  odoo_db: "prod",
  odoo_login: "admin",
  has_secret: { api_key: true },
});

export const passingTest: ConnectionTestResult = {
  ok: true,
  failed_step: null,
  steps: [
    { name: "url_valid", ok: true, detail: "https://api.suwe.test", hint: null },
    { name: "reachable", ok: true, detail: "the server answered", hint: null },
    { name: "tls", ok: true, detail: "TLS verified", hint: null },
    { name: "auth", ok: true, detail: "credentials accepted (HTTP 200)", hint: null },
  ],
};

export const failingTest: ConnectionTestResult = {
  ok: false,
  failed_step: "auth",
  steps: [
    { name: "url_valid", ok: true, detail: "https://api.suwe.test", hint: null },
    { name: "reachable", ok: true, detail: "the server answered", hint: null },
    { name: "tls", ok: true, detail: "TLS verified", hint: null },
    {
      name: "auth",
      ok: false,
      detail: "the server rejected the credentials (HTTP 401)",
      hint: "Check the key/token/client credentials.",
    },
  ],
};
