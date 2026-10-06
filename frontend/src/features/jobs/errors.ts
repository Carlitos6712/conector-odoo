import { ApiError } from "@/api/client";
import type { JobFieldErrors, JobFieldName } from "@/features/jobs/form";
import { describeResourceError } from "@/features/resources/errors";

export type JobAction = "save" | "delete" | "trigger" | "dryRun" | "toggle" | "load";

export interface DescribedJobError {
  messageKey: string;
  params?: Record<string, unknown>;
  /** Form field -> translation key, to show next to the offending input. */
  fieldErrors: JobFieldErrors;
  /** Server text worth showing (domain rule text, remote failures); clipped, never HTML. */
  detail?: string;
}

const MAX_DETAIL = 300;
const clip = (text: string): string | undefined =>
  text ? (text.length > MAX_DETAIL ? `${text.slice(0, MAX_DETAIL)}…` : text) : undefined;

/** `body.<request field>:` locations of pydantic errors -> wizard fields. */
const BODY_FIELDS: Record<string, JobFieldName> = {
  name: "name",
  batch_size: "batchSize",
  upsert_key: "upsertField",
  source: "sourceResource",
  target: "targetResource",
  mapping: "mapping",
  reverse_mapping: "reverseMapping",
  trigger: "cron",
  source_updated_field: "sourceUpdatedField",
  target_updated_field: "targetUpdatedField",
};

function bodyFields(detail: string): JobFieldErrors {
  const errors: JobFieldErrors = {};
  for (const part of detail.split(";")) {
    const match = /^\s*body\.([a-z_]+)(?:\.[^:]*)?:/.exec(part);
    const field = match?.[1] ? BODY_FIELDS[match[1]] : undefined;
    if (field) errors[field] = "jobs.errors.invalidField";
  }
  return errors;
}

/**
 * The backend raises `SyncJobInvalid` with English rule text (`application/jobs.py`,
 * `domain/sync.py`); recognising it by prefix lets the UI point at the right input.
 */
function ruleFields(detail: string): { fields: JobFieldErrors; messageKey?: string } {
  if (/^reverse mapping .* maps /.test(detail)) {
    return {
      fields: { reverseMapping: "jobs.errors.mappingMismatch" },
      messageKey: "jobs.errors.mappingMismatch",
    };
  }
  if (/^mapping .* maps .* but the job syncs/.test(detail)) {
    return {
      fields: { mapping: "jobs.errors.mappingMismatch" },
      messageKey: "jobs.errors.mappingMismatch",
    };
  }
  if (/needs a reverse mapping/.test(detail))
    return { fields: { reverseMapping: "jobs.errors.required" } };
  if (/^batch_size /.test(detail)) return { fields: { batchSize: "jobs.errors.batchSize" } };
  if (/^upsert_key /.test(detail)) return { fields: { upsertField: "jobs.errors.required" } };
  if (/^newest_wins /.test(detail)) {
    return {
      fields: {
        sourceUpdatedField: "jobs.errors.required",
        targetUpdatedField: "jobs.errors.required",
      },
    };
  }
  if (/^cron /.test(detail) || /^invalid cron/.test(detail)) {
    const code = /5 fields/.test(detail)
      ? "fields"
      : /out of range/.test(detail)
        ? "range"
        : "syntax";
    return { fields: { cron: `jobs.cron.errors.${code}` } };
  }
  if (/^webhook trigger /.test(detail)) return { fields: { eventTypes: "jobs.errors.eventTypes" } };
  return { fields: {} };
}

/** Maps an API failure to translation keys; request-level text is never shown unfiltered. */
export function describeJobError(error: unknown, action: JobAction): DescribedJobError {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      if (action === "delete") return { messageKey: "jobs.errors.inUse", fieldErrors: {} };
      if (action === "trigger" || action === "dryRun") {
        return { messageKey: "jobs.errors.alreadyRunning", fieldErrors: {} };
      }
      return {
        messageKey: "jobs.errors.nameTaken",
        fieldErrors: { name: "jobs.errors.nameTaken" },
      };
    }
    if (error.status === 404 && error.code === "not_found") {
      if (action === "save") {
        return {
          messageKey: "jobs.errors.referenceMissing",
          fieldErrors: { mapping: "jobs.errors.referenceMissing" },
          detail: clip(error.detail),
        };
      }
      return { messageKey: "jobs.errors.notFound", fieldErrors: {} };
    }
    if (error.status === 422) {
      const fromBody = bodyFields(error.detail);
      const rule = ruleFields(error.detail);
      const fieldErrors = { ...fromBody, ...rule.fields };
      return {
        messageKey: rule.messageKey ?? "jobs.errors.validation",
        fieldErrors,
        // Request-body locations already say which input is wrong; domain rule text and
        // unlocated failures are worth showing as the server worded them.
        detail:
          Object.keys(fromBody).length > 0 && Object.keys(rule.fields).length === 0
            ? undefined
            : clip(error.detail),
      };
    }
  }
  const shared = describeResourceError(error, "preview");
  return { ...shared, fieldErrors: {} };
}
