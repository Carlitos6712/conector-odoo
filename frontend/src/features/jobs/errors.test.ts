import { ApiError } from "@/api/client";
import { describeJobError } from "@/features/jobs/errors";

const api = (status: number, code: string, detail = "") => new ApiError({ status, code, detail });

describe("describeJobError", () => {
  it("explains a job that cannot be deleted because it has runs", () => {
    expect(describeJobError(api(409, "conflict", "job has runs"), "delete").messageKey).toBe(
      "jobs.errors.inUse",
    );
  });

  it("explains a run that is already in progress", () => {
    expect(describeJobError(api(409, "conflict", "already running"), "trigger").messageKey).toBe(
      "jobs.errors.alreadyRunning",
    );
  });

  it("points a taken name at the name field", () => {
    expect(describeJobError(api(409, "conflict", "name taken"), "save")).toMatchObject({
      messageKey: "jobs.errors.nameTaken",
      fieldErrors: { name: "jobs.errors.nameTaken" },
    });
  });

  it("maps a missing job on a manual run and a missing mapping on save", () => {
    expect(
      describeJobError(api(404, "not_found", "sync job 7 not found"), "trigger").messageKey,
    ).toBe("jobs.errors.notFound");
    expect(describeJobError(api(404, "not_found", "mapping 'x' not found"), "save")).toMatchObject({
      messageKey: "jobs.errors.referenceMissing",
      fieldErrors: { mapping: "jobs.errors.referenceMissing" },
    });
  });

  it("attaches a forward mapping mismatch to the mapping field", () => {
    const described = describeJobError(
      api(
        422,
        "validation_error",
        "mapping 'a' maps 'x' to 'y', but the job syncs 'clients' to 'res.partner'",
      ),
      "save",
    );
    expect(described.messageKey).toBe("jobs.errors.mappingMismatch");
    expect(described.fieldErrors).toEqual({ mapping: "jobs.errors.mappingMismatch" });
    expect(described.detail).toContain("maps 'x' to 'y'");
  });

  it("attaches a reverse mapping mismatch to the reverse field", () => {
    const described = describeJobError(
      api(422, "validation_error", "reverse mapping 'b' maps 'x' to 'y', but it must map ..."),
      "save",
    );
    expect(described.fieldErrors).toEqual({ reverseMapping: "jobs.errors.mappingMismatch" });
  });

  it("recognises other domain rules by their text", () => {
    expect(
      describeJobError(
        api(422, "validation_error", "direction bidirectional needs a reverse mapping"),
        "save",
      ).fieldErrors,
    ).toEqual({ reverseMapping: "jobs.errors.required" });
    expect(
      describeJobError(
        api(422, "validation_error", "batch_size must be between 1 and 1000"),
        "save",
      ).fieldErrors,
    ).toEqual({ batchSize: "jobs.errors.batchSize" });
    expect(
      describeJobError(
        api(422, "validation_error", "cron expression needs 5 fields (minute hour)"),
        "save",
      ).fieldErrors,
    ).toEqual({ cron: "jobs.cron.errors.fields" });
    expect(
      describeJobError(
        api(422, "validation_error", "newest_wins needs an updated-at field path for both sides"),
        "save",
      ).fieldErrors,
    ).toEqual({
      sourceUpdatedField: "jobs.errors.required",
      targetUpdatedField: "jobs.errors.required",
    });
  });

  it("maps request-body locations to form fields", () => {
    const described = describeJobError(
      api(
        422,
        "validation_error",
        "body.name: String should have at least 1 character; body.batch_size: x",
      ),
      "save",
    );
    expect(described.fieldErrors).toEqual({
      name: "jobs.errors.invalidField",
      batchSize: "jobs.errors.invalidField",
    });
    expect(described.detail).toBeUndefined();
  });

  it("shows clipped detail when nothing points at a field", () => {
    const described = describeJobError(api(422, "validation_error", "x".repeat(400)), "save");
    expect(described.messageKey).toBe("jobs.errors.validation");
    expect(described.detail?.length).toBeLessThanOrEqual(301);
  });

  it("keeps the retry delay on 429", () => {
    const limited = new ApiError({
      status: 429,
      code: "too_many_requests",
      detail: "",
      retryAfterSeconds: 9,
    });
    expect(describeJobError(limited, "trigger")).toMatchObject({
      messageKey: "resources.errors.rateLimited",
      params: { seconds: 9 },
    });
  });

  it("falls back to the shared remote and unexpected errors", () => {
    expect(describeJobError(api(502, "remote_unavailable", "boom"), "dryRun")).toMatchObject({
      messageKey: "resources.errors.remoteUnavailable",
      detail: "boom",
    });
    expect(describeJobError(new Error("secret"), "save")).toMatchObject({
      messageKey: "common.unexpectedError",
      fieldErrors: {},
    });
  });
});
