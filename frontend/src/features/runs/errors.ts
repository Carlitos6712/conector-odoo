import { ApiError } from "@/api/client";

export type RunAction = "load" | "cancel" | "resume" | "retryFailed";

export interface DescribedRunError {
  messageKey: string;
  params?: Record<string, unknown>;
}

/**
 * 409 carries one code (`conflict`) for several reasons; the English server text
 * (`RunNotResumable`, `JobAlreadyRunning`) tells them apart. Anything unrecognised keeps a
 * generic message: the raw text is never shown.
 */
function conflictKey(detail: string, action: RunAction): string {
  if (/already has an active run/.test(detail)) return "runs.errors.jobBusy";
  if (/is not active/.test(detail)) return "runs.errors.notActive";
  if (/still active/.test(detail)) return "runs.errors.stillActive";
  if (/already finished/.test(detail)) return "runs.errors.notResumable";
  if (/no failed records/.test(detail)) return "runs.errors.nothingToRetry";
  return action === "cancel" ? "runs.errors.notActive" : "runs.errors.conflict";
}

export function describeRunError(error: unknown, action: RunAction): DescribedRunError {
  if (!(error instanceof ApiError)) return { messageKey: "common.unexpectedError" };
  if (error.code === "network_error") return { messageKey: "common.networkError" };
  if (error.status === 409) return { messageKey: conflictKey(error.detail, action) };
  if (error.status === 404) return { messageKey: "runs.errors.notFound" };
  if (error.status === 429) {
    return error.retryAfterSeconds === null
      ? { messageKey: "runs.errors.rateLimitedUnknown" }
      : { messageKey: "runs.errors.rateLimited", params: { seconds: error.retryAfterSeconds } };
  }
  return { messageKey: "common.unexpectedError" };
}
