import { ApiError } from "@/api/client";
import { describeRunError } from "@/features/runs/errors";

const api = (status: number, code: string, detail = "", retryAfterSeconds: number | null = null) =>
  new ApiError({ status, code, detail, retryAfterSeconds });

describe("describeRunError", () => {
  it("explains a cancel on a run that is no longer active", () => {
    expect(describeRunError(api(409, "conflict", "run 3 is not active"), "cancel").messageKey).toBe(
      "runs.errors.notActive",
    );
  });

  it("tells a resume that cannot happen because the run finished or is still alive", () => {
    expect(
      describeRunError(api(409, "conflict", "run 3 already finished (partial)"), "resume")
        .messageKey,
    ).toBe("runs.errors.notResumable");
    expect(
      describeRunError(api(409, "conflict", "run 3 is still active"), "resume").messageKey,
    ).toBe("runs.errors.stillActive");
  });

  it("recognises a job that already has an active run", () => {
    const detail = "sync job 7 already has an active run";
    expect(describeRunError(api(409, "conflict", detail), "resume").messageKey).toBe(
      "runs.errors.jobBusy",
    );
    expect(describeRunError(api(409, "conflict", detail), "retryFailed").messageKey).toBe(
      "runs.errors.jobBusy",
    );
  });

  it("explains a retry with nothing to retry", () => {
    expect(
      describeRunError(api(409, "conflict", "run 3 has no failed records to retry"), "retryFailed")
        .messageKey,
    ).toBe("runs.errors.nothingToRetry");
  });

  it("falls back to a generic conflict for an unknown 409 text", () => {
    expect(describeRunError(api(409, "conflict", "???"), "resume").messageKey).toBe(
      "runs.errors.conflict",
    );
  });

  it("maps a missing run or job", () => {
    expect(describeRunError(api(404, "not_found", "sync run 3 not found"), "load").messageKey).toBe(
      "runs.errors.notFound",
    );
    expect(
      describeRunError(api(404, "not_found", "sync job 7 not found"), "resume").messageKey,
    ).toBe("runs.errors.notFound");
  });

  it("reports the delay on 429", () => {
    expect(describeRunError(api(429, "rate_limited", "", 12), "cancel")).toMatchObject({
      messageKey: "runs.errors.rateLimited",
      params: { seconds: 12 },
    });
    expect(describeRunError(api(429, "rate_limited"), "cancel").messageKey).toBe(
      "runs.errors.rateLimitedUnknown",
    );
  });

  it("falls back to the shared messages for network and unknown failures", () => {
    expect(describeRunError(api(0, "network_error"), "load").messageKey).toBe(
      "common.networkError",
    );
    expect(describeRunError(new Error("x"), "load").messageKey).toBe("common.unexpectedError");
  });
});
