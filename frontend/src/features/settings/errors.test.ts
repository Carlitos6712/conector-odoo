import { ApiError } from "@/api/client";
import { describeAccountError, describeUserError } from "@/features/settings/errors";

const err = (status: number, code: string, detail = "", retryAfterSeconds: number | null = null) =>
  new ApiError({ status, code, detail, retryAfterSeconds });

describe("describeUserError", () => {
  it("maps a taken username on create to a field error", () => {
    const d = describeUserError(err(409, "conflict", "username taken"), "create");
    expect(d.messageKey).toBe("settings.users.errors.usernameTaken");
    expect(d.field).toBe("username");
  });

  it("explains the last-admin conflict on update and delete", () => {
    const text = "the last administrator cannot be demoted";
    expect(describeUserError(err(409, "conflict", text), "update").messageKey).toBe(
      "settings.users.errors.lastAdmin",
    );
    expect(
      describeUserError(err(409, "conflict", "the last administrator cannot be deleted"), "delete")
        .messageKey,
    ).toBe("settings.users.errors.lastAdmin");
  });

  it("maps a policy violation on the password to the password field", () => {
    const d = describeUserError(
      err(422, "validation_error", "password must be at least 12 characters long"),
      "create",
    );
    expect(d.messageKey).toBe("settings.users.errors.passwordPolicy");
    expect(d.field).toBe("password");
  });

  it("maps request validation of the body to the right field", () => {
    expect(
      describeUserError(err(422, "validation_error", "body.password: String too short"), "reset")
        .field,
    ).toBe("password");
    expect(
      describeUserError(err(422, "validation_error", "body.username: String too short"), "create")
        .field,
    ).toBe("username");
  });

  it("shows a username rule on its field", () => {
    const d = describeUserError(
      err(422, "validation_error", "username must have 1 to 64 characters"),
      "create",
    );
    expect(d.field).toBe("username");
  });

  it("explains you cannot delete your own account", () => {
    expect(
      describeUserError(
        err(422, "validation_error", "you cannot delete your own account"),
        "delete",
      ).messageKey,
    ).toBe("settings.users.errors.deleteSelf");
  });

  it("maps 404 to user-gone and 403 to forbidden", () => {
    expect(describeUserError(err(404, "not_found"), "delete").messageKey).toBe(
      "settings.users.errors.notFound",
    );
    expect(describeUserError(err(403, "forbidden"), "create").messageKey).toBe(
      "settings.users.errors.forbidden",
    );
  });

  it("falls back to the shared messages", () => {
    expect(describeUserError(err(0, "network_error"), "create").messageKey).toBe(
      "common.networkError",
    );
    expect(describeUserError(new Error("x"), "create").messageKey).toBe("common.unexpectedError");
  });
});

describe("describeAccountError", () => {
  it("flags a wrong current password on its field", () => {
    const d = describeAccountError(err(422, "invalid_current_password", "nope"));
    expect(d.messageKey).toBe("settings.account.errors.currentWrong");
    expect(d.field).toBe("current");
  });

  it("flags the policy and reuse rules on the new password", () => {
    expect(
      describeAccountError(
        err(422, "validation_error", "password must be at least 12 characters long"),
      ).field,
    ).toBe("next");
    const same = describeAccountError(
      err(422, "validation_error", "the new password must differ from the current one"),
    );
    expect(same.messageKey).toBe("settings.account.errors.same");
    expect(same.field).toBe("next");
  });

  it("reports the lockout with its delay", () => {
    const d = describeAccountError(err(429, "too_many_attempts", "", 120));
    expect(d.messageKey).toBe("settings.account.errors.rateLimited");
    expect(d.params).toEqual({ seconds: 120 });
    expect(describeAccountError(err(429, "too_many_attempts")).messageKey).toBe(
      "settings.account.errors.rateLimitedUnknown",
    );
  });

  it("falls back to the shared messages", () => {
    expect(describeAccountError(err(0, "network_error")).messageKey).toBe("common.networkError");
    expect(describeAccountError(err(500, "http_error")).messageKey).toBe("common.unexpectedError");
  });
});
