import { ApiError } from "@/api/client";
import { describeMappingError } from "@/features/mappings/errors";

const api = (status: number, code: string, detail = "", extra: Record<string, unknown> = {}) =>
  new ApiError({ status, code, detail, extra });

describe("describeMappingError", () => {
  it("explains a mapping in use on delete", () => {
    expect(describeMappingError(api(409, "conflict"), "delete").messageKey).toBe(
      "mappings.errors.inUse",
    );
  });

  it("reports other conflicts generically", () => {
    expect(describeMappingError(api(409, "conflict"), "save").messageKey).toBe(
      "mappings.errors.conflict",
    );
  });

  it("returns structured 422 issues with their paths", () => {
    const described = describeMappingError(
      api(422, "validation_error", "rules[0].target: duplicate", {
        issues: [
          { path: "rules[0].target", severity: "error", message: "duplicate target 'a'" },
          { path: "target.name", severity: "warning", message: "w" },
          { nonsense: true },
        ],
      }),
      "save",
    );
    expect(described.messageKey).toBe("mappings.errors.validation");
    expect(described.issues).toEqual([
      { path: "rules[0].target", severity: "error", message: "duplicate target 'a'" },
      { path: "target.name", severity: "warning", message: "w" },
    ]);
    expect(described.detail).toBeUndefined();
  });

  it("parses the path of a codec error out of the flat detail", () => {
    const described = describeMappingError(
      api(422, "validation_error", "rules[2].expr.steps[1]: unknown step type 'x'"),
      "save",
    );
    expect(described.issues).toEqual([
      { path: "rules[2].expr.steps[1]", severity: "error", message: "unknown step type 'x'" },
    ]);
  });

  it("shows clipped detail when it points at no rule", () => {
    const described = describeMappingError(api(422, "validation_error", "x".repeat(400)), "save");
    expect(described.issues).toEqual([]);
    expect(described.detail?.length).toBeLessThanOrEqual(301);
  });

  it("maps a missing mapping or schema", () => {
    expect(describeMappingError(api(404, "not_found"), "load").messageKey).toBe(
      "mappings.errors.notFound",
    );
    expect(describeMappingError(api(404, "resource_not_found", "gone"), "dryRun").messageKey).toBe(
      "resources.errors.remoteNotFound",
    );
  });

  it("keeps the retry delay on 429 and the remote codes", () => {
    const limited = new ApiError({
      status: 429,
      code: "too_many_requests",
      detail: "",
      retryAfterSeconds: 7,
    });
    expect(describeMappingError(limited, "dryRun")).toMatchObject({
      messageKey: "resources.errors.rateLimited",
      params: { seconds: 7 },
    });
    expect(describeMappingError(api(502, "remote_unavailable", "boom"), "dryRun")).toMatchObject({
      messageKey: "resources.errors.remoteUnavailable",
      detail: "boom",
    });
  });

  it("does not leak unknown errors", () => {
    expect(describeMappingError(new Error("secret"), "save")).toMatchObject({
      messageKey: "common.unexpectedError",
      issues: [],
    });
  });
});
