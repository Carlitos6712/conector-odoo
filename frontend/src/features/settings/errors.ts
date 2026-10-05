import { ApiError } from "@/api/client";

export type UserAction = "create" | "update" | "reset" | "delete";
export type UserField = "username" | "password";
export type AccountField = "current" | "next";

export interface DescribedSettingsError<F extends string> {
  messageKey: string;
  params?: Record<string, unknown>;
  /** The input the message belongs next to, when there is one. */
  field?: F;
}

/** Network and unexpected failures share the app-wide messages. */
function shared(error: unknown): DescribedSettingsError<never> {
  if (error instanceof ApiError && error.code === "network_error") {
    return { messageKey: "common.networkError" };
  }
  return { messageKey: "common.unexpectedError" };
}

/**
 * The backend words domain rules in English (`application/auth.py`, `domain/auth.py`); matching
 * the text is the only way to tell them apart, as they share status 409/422.
 */
export function describeUserError(
  error: unknown,
  action: UserAction,
): DescribedSettingsError<UserField> {
  if (error instanceof ApiError) {
    const detail = error.detail;
    if (error.status === 409) {
      // Only creating can clash on the name; update and delete conflict on the last admin.
      if (action === "create" && !/last administrator/.test(detail)) {
        return { messageKey: "settings.users.errors.usernameTaken", field: "username" };
      }
      return { messageKey: "settings.users.errors.lastAdmin" };
    }
    if (error.status === 404) return { messageKey: "settings.users.errors.notFound" };
    if (error.status === 403) return { messageKey: "settings.users.errors.forbidden" };
    if (error.status === 422) {
      if (/your own account/.test(detail))
        return { messageKey: "settings.users.errors.deleteSelf" };
      if (/^password /.test(detail) || /^body\.password\b/.test(detail)) {
        return { messageKey: "settings.users.errors.passwordPolicy", field: "password" };
      }
      if (/^username /.test(detail) || /^body\.username\b/.test(detail)) {
        return { messageKey: "settings.users.errors.usernameInvalid", field: "username" };
      }
      return { messageKey: "settings.users.errors.invalid" };
    }
  }
  return shared(error);
}

export function describeAccountError(error: unknown): DescribedSettingsError<AccountField> {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return error.retryAfterSeconds
        ? {
            messageKey: "settings.account.errors.rateLimited",
            params: { seconds: error.retryAfterSeconds },
          }
        : { messageKey: "settings.account.errors.rateLimitedUnknown" };
    }
    if (error.code === "invalid_current_password") {
      return { messageKey: "settings.account.errors.currentWrong", field: "current" };
    }
    if (error.status === 422) {
      if (/must differ/.test(error.detail)) {
        return { messageKey: "settings.account.errors.same", field: "next" };
      }
      return { messageKey: "settings.account.errors.policy", field: "next" };
    }
  }
  return shared(error);
}
