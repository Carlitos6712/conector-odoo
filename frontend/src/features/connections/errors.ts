import { ApiError } from "@/api/client";

export type ProfileAction = "save" | "delete" | "test";

export interface DescribedError {
  messageKey: string;
  params?: Record<string, unknown>;
  /** Form field -> translation key, for 422s that point at a request field. */
  fieldErrors: Record<string, string>;
}

/** 422 details look like `body.name: msg; body.base_url: msg`. */
function fieldsOf(detail: string): string[] {
  const fields = new Set<string>();
  for (const part of detail.split(";")) {
    const match = /^\s*body\.([a-z_]+)(?:\.[^:]*)?:/.exec(part);
    if (match?.[1]) fields.add(match[1]);
  }
  return [...fields];
}

/** Maps an API failure to translation keys; the raw server text is never shown. */
export function describeProfileError(error: unknown, action: ProfileAction): DescribedError {
  if (!(error instanceof ApiError)) {
    return { messageKey: "common.unexpectedError", fieldErrors: {} };
  }
  if (error.code === "network_error") {
    return { messageKey: "common.networkError", fieldErrors: {} };
  }
  if (error.status === 409) {
    if (action === "delete") return { messageKey: "connections.errors.inUse", fieldErrors: {} };
    const key = "connections.errors.nameTaken";
    return { messageKey: key, fieldErrors: { name: key } };
  }
  if (error.status === 422) {
    const fields = fieldsOf(error.detail);
    if (fields.length > 0) {
      return {
        messageKey: "connections.errors.validation",
        fieldErrors: Object.fromEntries(fields.map((f) => [f, "connections.errors.invalidField"])),
      };
    }
    return { messageKey: "connections.errors.validation", fieldErrors: {} };
  }
  if (error.status === 429) {
    return error.retryAfterSeconds === null
      ? { messageKey: "connections.errors.rateLimitedUnknown", fieldErrors: {} }
      : {
          messageKey: "connections.errors.rateLimited",
          params: { seconds: error.retryAfterSeconds },
          fieldErrors: {},
        };
  }
  if (error.code === "vault_not_configured") {
    return { messageKey: "connections.errors.vaultMissing", fieldErrors: {} };
  }
  if (error.status === 403) return { messageKey: "connections.errors.forbidden", fieldErrors: {} };
  if (error.status === 404) return { messageKey: "connections.errors.notFound", fieldErrors: {} };
  return { messageKey: "common.unexpectedError", fieldErrors: {} };
}
