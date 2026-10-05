import { ApiError } from "@/api/client";

export type ResourceAction = "save" | "delete" | "preview" | "import" | "discover" | "load";

export interface DescribedResourceError {
  messageKey: string;
  params?: Record<string, unknown>;
  /** Form field -> translation key, for 422s that point at a request field. */
  fieldErrors: Record<string, string>;
  /**
   * Server text worth showing next to the message (remote failures, import problems). The API
   * already masks secrets in it; it is rendered as plain text and truncated.
   */
  detail?: string;
}

const MAX_DETAIL = 300;

function fieldsOf(detail: string): string[] {
  const fields = new Set<string>();
  for (const part of detail.split(";")) {
    const match = /^\s*body\.([a-z_]+)(?:\.[^:]*)?:/.exec(part);
    if (match?.[1]) fields.add(match[1]);
  }
  return [...fields];
}

const clip = (text: string): string | undefined =>
  text ? (text.length > MAX_DETAIL ? `${text.slice(0, MAX_DETAIL)}…` : text) : undefined;

/** Maps an API failure to translation keys; request-level text is never shown raw. */
export function describeResourceError(
  error: unknown,
  action: ResourceAction,
): DescribedResourceError {
  if (!(error instanceof ApiError)) {
    return { messageKey: "common.unexpectedError", fieldErrors: {} };
  }
  if (error.code === "network_error") {
    return { messageKey: "common.networkError", fieldErrors: {} };
  }
  if (error.status === 409) {
    return {
      messageKey: action === "delete" ? "resources.errors.inUse" : "resources.errors.conflict",
      fieldErrors: {},
    };
  }
  if (error.status === 422) {
    if (action === "import") {
      return {
        messageKey: "resources.errors.importFailed",
        fieldErrors: {},
        detail: clip(error.detail),
      };
    }
    const fields = fieldsOf(error.detail);
    return {
      messageKey: "resources.errors.validation",
      fieldErrors: Object.fromEntries(fields.map((f) => [f, "resources.errors.invalidField"])),
      detail: fields.length === 0 ? clip(error.detail) : undefined,
    };
  }
  if (error.status === 429) {
    return error.retryAfterSeconds === null
      ? { messageKey: "resources.errors.rateLimitedUnknown", fieldErrors: {} }
      : {
          messageKey: "resources.errors.rateLimited",
          params: { seconds: error.retryAfterSeconds },
          fieldErrors: {},
        };
  }
  if (error.code === "remote_auth_error") {
    return {
      messageKey: "resources.errors.remoteAuth",
      fieldErrors: {},
      detail: clip(error.detail),
    };
  }
  if (error.code === "remote_unavailable" || error.code === "odoo_unavailable") {
    return {
      messageKey: "resources.errors.remoteUnavailable",
      fieldErrors: {},
      detail: clip(error.detail),
    };
  }
  if (error.code === "resource_not_found") {
    return {
      messageKey: "resources.errors.remoteNotFound",
      fieldErrors: {},
      detail: clip(error.detail),
    };
  }
  if (error.code === "permission_denied") {
    return {
      messageKey: "resources.errors.remotePermission",
      fieldErrors: {},
      detail: clip(error.detail),
    };
  }
  if (error.code === "vault_not_configured") {
    return { messageKey: "resources.errors.vaultMissing", fieldErrors: {} };
  }
  if (error.status === 403) return { messageKey: "resources.errors.forbidden", fieldErrors: {} };
  if (error.status === 404) return { messageKey: "resources.errors.notFound", fieldErrors: {} };
  return { messageKey: "common.unexpectedError", fieldErrors: {} };
}
