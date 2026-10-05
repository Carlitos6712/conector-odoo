import { ApiError } from "@/api/client";
import { describeResourceError } from "@/features/resources/errors";

const err = (status: number, code: string, detail = "", retry: number | null = null) =>
  new ApiError({ status, code, detail, retryAfterSeconds: retry });

describe("describeResourceError", () => {
  it("explains a resource that is still in use when deleting", () => {
    expect(describeResourceError(err(409, "conflict", "in use"), "delete").messageKey).toBe(
      "resources.errors.inUse",
    );
  });

  it("reports a plain conflict when saving", () => {
    expect(describeResourceError(err(409, "conflict"), "save").messageKey).toBe(
      "resources.errors.conflict",
    );
  });

  it("maps 422 body locations to field errors without echoing the text", () => {
    const result = describeResourceError(
      err(422, "validation_error", "body.id_field: Field required; body.pagination.max_pages: bad"),
      "save",
    );
    expect(result.fieldErrors).toEqual({
      id_field: "resources.errors.invalidField",
      pagination: "resources.errors.invalidField",
    });
    expect(result.detail).toBeUndefined();
  });

  it("keeps the domain validation message as detail when no field is named", () => {
    const result = describeResourceError(
      err(422, "validation_error", "get endpoint path must contain {id}"),
      "save",
    );
    expect(result.messageKey).toBe("resources.errors.validation");
    expect(result.detail).toBe("get endpoint path must contain {id}");
  });

  it("reports an import failure with the server explanation", () => {
    const result = describeResourceError(
      err(422, "import_failed", "not an OpenAPI document"),
      "import",
    );
    expect(result.messageKey).toBe("resources.errors.importFailed");
    expect(result.detail).toBe("not an OpenAPI document");
  });

  it("maps remote failures and truncates long details", () => {
    const long = "x".repeat(900);
    const result = describeResourceError(err(502, "remote_unavailable", long), "preview");
    expect(result.messageKey).toBe("resources.errors.remoteUnavailable");
    expect(result.detail?.length).toBeLessThan(400);
    expect(describeResourceError(err(502, "remote_auth_error", "401"), "preview").messageKey).toBe(
      "resources.errors.remoteAuth",
    );
    expect(describeResourceError(err(404, "resource_not_found", "x"), "preview").messageKey).toBe(
      "resources.errors.remoteNotFound",
    );
  });

  it("distinguishes an Odoo access denial from a missing role", () => {
    expect(describeResourceError(err(403, "permission_denied", "x"), "discover").messageKey).toBe(
      "resources.errors.remotePermission",
    );
  });

  it("maps 429 with and without Retry-After", () => {
    const known = describeResourceError(err(429, "rate_limited", "", 12), "save");
    expect(known.messageKey).toBe("resources.errors.rateLimited");
    expect(known.params).toEqual({ seconds: 12 });
    expect(describeResourceError(err(429, "rate_limited"), "save").messageKey).toBe(
      "resources.errors.rateLimitedUnknown",
    );
  });

  it("falls back to generic messages", () => {
    expect(describeResourceError(new Error("boom"), "save").messageKey).toBe(
      "common.unexpectedError",
    );
    expect(describeResourceError(err(0, "network_error"), "save").messageKey).toBe(
      "common.networkError",
    );
    expect(describeResourceError(err(403, "forbidden"), "save").messageKey).toBe(
      "resources.errors.forbidden",
    );
    expect(describeResourceError(err(404, "not_found"), "load").messageKey).toBe(
      "resources.errors.notFound",
    );
  });
});
