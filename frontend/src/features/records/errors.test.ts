import { ApiError } from "@/api/client";
import { describeRecordError } from "@/features/records/errors";

const err = (status: number, code: string, detail = "") => new ApiError({ status, code, detail });

describe("describeRecordError", () => {
  it("passes Odoo's refusal of a delete through as detail", () => {
    const out = describeRecordError(
      err(422, "validation_error", "cannot delete res.partner 7: x"),
      "delete",
    );
    expect(out).toMatchObject({
      messageKey: "records.errors.refused",
      detail: "cannot delete res.partner 7: x",
    });
  });

  it("flags validation errors of a save", () => {
    expect(describeRecordError(err(422, "validation_error", "d"), "save").validation).toBe(true);
  });

  it("distinguishes a missing record from a missing model", () => {
    expect(describeRecordError(err(404, "resource_not_found"), "delete").messageKey).toBe(
      "records.errors.gone",
    );
    expect(describeRecordError(err(404, "resource_not_found"), "load").messageKey).toBe(
      "records.errors.modelNotFound",
    );
  });

  it("clips very long details and handles transport failures", () => {
    expect(
      describeRecordError(err(422, "validation_error", "x".repeat(500)), "delete").detail,
    ).toHaveLength(301);
    expect(describeRecordError(err(0, "network_error"), "load").messageKey).toBe(
      "common.networkError",
    );
    expect(describeRecordError(new Error("boom"), "load").messageKey).toBe(
      "common.unexpectedError",
    );
  });
});
