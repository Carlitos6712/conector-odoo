export type ProfileKind = "odoo" | "rest";
export type AuthMethod = "api_key" | "bearer" | "oauth2_client_credentials" | "oidc";

export const SECRET_FIELDS = [
  "api_key",
  "token",
  "client_id",
  "client_secret",
  "password",
] as const;
export type SecretField = (typeof SECRET_FIELDS)[number];

/** A profile as the API returns it: credentials are never included, only `has_secret` flags. */
export interface Profile {
  id: number;
  name: string;
  type: ProfileKind;
  base_url: string;
  auth_method: AuthMethod;
  extra_headers: Record<string, string>;
  tls_verify: boolean;
  timeout_seconds: number;
  odoo_db: string | null;
  odoo_login: string | null;
  token_url: string | null;
  scope: string | null;
  api_key_header: string;
  has_secret: Partial<Record<SecretField, boolean>>;
  created_at: string | null;
  updated_at: string | null;
}

/** Write-only credentials. A missing key keeps the stored value on update. */
export type SecretsInput = Partial<Record<SecretField, string>>;

export interface ProfileInput {
  name: string;
  type: ProfileKind;
  base_url: string;
  auth_method: AuthMethod;
  extra_headers?: Record<string, string>;
  tls_verify?: boolean;
  timeout_seconds?: number;
  odoo_db?: string | null;
  odoo_login?: string | null;
  token_url?: string | null;
  scope?: string | null;
  api_key_header?: string;
  secrets?: SecretsInput;
}

export interface ProbeStep {
  name: string;
  ok: boolean;
  detail: string;
  hint: string | null;
}

export interface ConnectionTestResult {
  ok: boolean;
  failed_step: string | null;
  steps: ProbeStep[];
}
