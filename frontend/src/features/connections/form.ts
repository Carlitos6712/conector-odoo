import type {
  AuthMethod,
  Profile,
  ProfileInput,
  ProfileKind,
  SecretField,
  SecretsInput,
} from "@/features/connections/types";

export const AUTH_METHODS: readonly AuthMethod[] = [
  "api_key",
  "bearer",
  "oauth2_client_credentials",
  "oidc",
];

export interface FormState {
  type: ProfileKind | null;
  name: string;
  base_url: string;
  odoo_db: string;
  odoo_login: string;
  auth_method: AuthMethod;
  api_key_header: string;
  token_url: string;
  scope: string;
  tls_verify: boolean;
  timeout_seconds: string;
  /** Headers are not editable here, but a PUT replaces them, so they travel unchanged. */
  extra_headers: Record<string, string>;
  /** Typed credentials: form state only, gone when the wizard unmounts. */
  secrets: Record<SecretField, string>;
}

export type FieldErrors = Record<string, string>;

export const emptyState = (): FormState => ({
  type: null,
  name: "",
  base_url: "",
  odoo_db: "",
  odoo_login: "",
  auth_method: "bearer",
  api_key_header: "X-API-Key",
  token_url: "",
  scope: "",
  tls_verify: true,
  timeout_seconds: "30",
  extra_headers: {},
  secrets: { api_key: "", token: "", client_id: "", client_secret: "", password: "" },
});

export const stateFromProfile = (profile: Profile): FormState => ({
  ...emptyState(),
  type: profile.type,
  name: profile.name,
  base_url: profile.base_url,
  odoo_db: profile.odoo_db ?? "",
  odoo_login: profile.odoo_login ?? "",
  auth_method: profile.auth_method,
  api_key_header: profile.api_key_header,
  token_url: profile.token_url ?? "",
  scope: profile.scope ?? "",
  tls_verify: profile.tls_verify,
  timeout_seconds: String(profile.timeout_seconds),
  extra_headers: profile.extra_headers,
});

/** Credentials each kind/auth type needs. */
export function requiredSecrets(state: FormState): SecretField[] {
  if (state.type === "odoo") return ["api_key"];
  switch (state.auth_method) {
    case "api_key":
      return ["api_key"];
    case "bearer":
      return ["token"];
    default:
      return ["client_id", "client_secret"];
  }
}

export const usesTokenUrl = (state: FormState) =>
  state.type === "rest" &&
  (state.auth_method === "oauth2_client_credentials" || state.auth_method === "oidc");

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return (url.protocol === "http:" || url.protocol === "https:") && url.hostname !== "";
  } catch {
    return false;
  }
}

const REQUIRED = "connections.validation.required";
const INVALID_URL = "connections.validation.url";

/** Step 1 (kind) and step 2 (data) rules; `stored` are the secrets already saved on the server. */
export function validate(
  step: "kind" | "data",
  state: FormState,
  stored: Profile["has_secret"] = {},
): FieldErrors {
  const errors: FieldErrors = {};
  if (step === "kind") {
    if (!state.type) errors.type = "connections.validation.kind";
    return errors;
  }
  if (!state.name.trim()) errors.name = "connections.validation.name";
  if (!state.base_url.trim()) errors.base_url = REQUIRED;
  else if (!isHttpUrl(state.base_url)) errors.base_url = INVALID_URL;
  const timeout = Number(state.timeout_seconds);
  if (!state.timeout_seconds.trim() || !Number.isFinite(timeout) || timeout <= 0)
    errors.timeout_seconds = "connections.validation.timeout";

  if (state.type === "odoo") {
    if (!state.odoo_db.trim()) errors.odoo_db = REQUIRED;
    if (!state.odoo_login.trim()) errors.odoo_login = REQUIRED;
  } else {
    if (state.auth_method === "api_key" && !state.api_key_header.trim())
      errors.api_key_header = REQUIRED;
    if (usesTokenUrl(state)) {
      const tokenUrl = state.token_url.trim();
      if (!tokenUrl && state.auth_method === "oauth2_client_credentials")
        errors.token_url = REQUIRED;
      else if (tokenUrl && !isHttpUrl(tokenUrl)) errors.token_url = INVALID_URL;
    }
  }
  for (const field of requiredSecrets(state)) {
    if (!state.secrets[field].trim() && !stored[field]) errors[field] = REQUIRED;
  }
  return errors;
}

/** True when every credential the draft test needs has been typed (stored ones are unreadable). */
export const hasAllSecretsTyped = (state: FormState) =>
  requiredSecrets(state).every((field) => state.secrets[field].trim() !== "");

/** Builds the request body with only the fields relevant to the chosen kind and auth type. */
export function toInput(state: FormState): ProfileInput {
  const secrets: SecretsInput = {};
  for (const field of requiredSecrets(state)) {
    if (state.secrets[field] !== "") secrets[field] = state.secrets[field];
  }
  const base = {
    name: state.name.trim(),
    base_url: state.base_url.trim(),
    extra_headers: state.extra_headers,
    tls_verify: state.tls_verify,
    timeout_seconds: Number(state.timeout_seconds),
    ...(Object.keys(secrets).length > 0 ? { secrets } : {}),
  };
  if (state.type === "odoo") {
    return {
      ...base,
      type: "odoo",
      auth_method: "api_key",
      odoo_db: state.odoo_db.trim(),
      odoo_login: state.odoo_login.trim(),
    };
  }
  return {
    ...base,
    type: "rest",
    auth_method: state.auth_method,
    ...(state.auth_method === "api_key" ? { api_key_header: state.api_key_header.trim() } : {}),
    ...(usesTokenUrl(state)
      ? { token_url: state.token_url.trim() || null, scope: state.scope.trim() || null }
      : {}),
  };
}
