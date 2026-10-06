import type { ActiveOdoo, ConnectionTestResult, Profile } from "@/features/connections/types";

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
    is_active: false,
    last_connected_at: null,
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

/** An active Odoo connection backed by `odooProfileFixture`. */
export function activeOdooFixture(overrides: Partial<ActiveOdoo> = {}): ActiveOdoo {
  return {
    source: "profile",
    profile_id: 2,
    profile_name: "Odoo producción",
    base_url: "https://odoo.example.com",
    db: "prod",
    login: "admin",
    last_connected_at: "2026-03-01T10:00:00Z",
    status: "active",
    warning: null,
    ...overrides,
  };
}

export const noOdooFixture = activeOdooFixture({
  source: "none",
  profile_id: null,
  profile_name: null,
  base_url: null,
  db: null,
  login: null,
  last_connected_at: null,
  status: "not_configured",
});

/** What the API answers (422) when the probe of the profile to activate fails. */
export const activationFailure = {
  error: "odoo_activation_failed",
  detail: "the Odoo connection could not be activated",
  failed_step: "auth",
  steps: failingTest.steps,
};
