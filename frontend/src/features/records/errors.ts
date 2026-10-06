import { ApiError } from "@/api/client";

export type RecordAction = "load" | "save" | "delete";

export interface DescribedRecordError {
  messageKey: string;
  /** Server text worth showing as plain text (Odoo's own refusal), truncated. */
  detail?: string;
  /** True for a 422 on save: the detail may point at individual form fields. */
  validation: boolean;
}

const MAX_DETAIL = 300;
const clip = (text: string): string | undefined =>
  text ? (text.length > MAX_DETAIL ? `${text.slice(0, MAX_DETAIL)}…` : text) : undefined;

/** Maps an API failure to a translation key; Odoo's refusal text is passed through as detail. */
export function describeRecordError(error: unknown, action: RecordAction): DescribedRecordError {
  const plain = (messageKey: string, detail?: string): DescribedRecordError => ({
    messageKey,
    detail,
    validation: false,
  });
  if (!(error instanceof ApiError)) return plain("common.unexpectedError");
  if (error.code === "network_error") return plain("common.networkError");
  if (error.status === 404) {
    return plain(action === "load" ? "records.errors.modelNotFound" : "records.errors.gone");
  }
  if (error.status === 422) {
    return {
      messageKey: action === "delete" ? "records.errors.refused" : "records.errors.invalid",
      detail: clip(error.detail),
      validation: action === "save",
    };
  }
  if (error.status === 403) return plain("resources.errors.forbidden");
  if (error.code === "vault_not_configured") return plain("resources.errors.vaultMissing");
  if (error.code === "remote_auth_error") {
    return plain("resources.errors.remoteAuth", clip(error.detail));
  }
  if (error.code === "remote_unavailable" || error.code === "odoo_unavailable") {
    return plain("resources.errors.remoteUnavailable", clip(error.detail));
  }
  return plain("common.unexpectedError");
}
