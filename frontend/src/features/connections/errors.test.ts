import { ApiError } from "@/api/client";
import { describeProfileError } from "@/features/connections/errors";

const err = (status: number, code: string, detail = "", retry: number | null = null) =>
  new ApiError({ status, code, detail, retryAfterSeconds: retry });

describe("describeProfileError", () => {
  it("explains a profile that is still in use when deleting", () => {
    expect(describeProfileError(err(409, "conflict", "in use"), "delete").messageKey).toBe(
      "connections.errors.inUse",
    );
  });

  it("reports a taken name as a field error when saving", () => {
    const result = describeProfileError(err(409, "conflict", "name taken"), "save");
    expect(result.fieldErrors).toEqual({ name: "connections.errors.nameTaken" });
    expect(result.messageKey).toBe("connections.errors.nameTaken");
  });

  it("maps 422 locations to field errors", () => {
    const result = describeProfileError(
      err(
        422,
        "validation_error",
        "body.name: String should have at least 1 character; body.base_url: Field required",
      ),
      "save",
    );
    expect(result.fieldErrors).toEqual({
      name: "connections.errors.invalidField",
      base_url: "connections.errors.invalidField",
    });
  });

  it("maps 422 without a field to a general validation message", () => {
    const result = describeProfileError(
      err(422, "validation_error", "timeout_seconds must be greater than 0"),
      "save",
    );
    expect(result.fieldErrors).toEqual({});
    expect(result.messageKey).toBe("connections.errors.validation");
  });

  it("carries the retry delay on 429", () => {
    const result = describeProfileError(err(429, "too_many_attempts", "", 30), "save");
    expect(result.messageKey).toBe("connections.errors.rateLimited");
    expect(result.params).toEqual({ seconds: 30 });
  });

  it("covers vault, network and unknown failures", () => {
    expect(describeProfileError(err(503, "vault_not_configured"), "save").messageKey).toBe(
      "connections.errors.vaultMissing",
    );
    expect(describeProfileError(err(0, "network_error"), "save").messageKey).toBe(
      "common.networkError",
    );
    expect(describeProfileError(new Error("x"), "save").messageKey).toBe("common.unexpectedError");
  });
});
