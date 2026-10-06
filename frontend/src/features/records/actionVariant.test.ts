import { describe, expect, it } from "vitest";
import { actionVariant } from "@/features/records/actionVariant";

describe("actionVariant", () => {
  it("maps each propagation action to a semantic badge variant", () => {
    expect(actionVariant("created")).toBe("success");
    expect(actionVariant("updated")).toBe("info");
    expect(actionVariant("deleted")).toBe("warning");
    expect(actionVariant("skipped")).toBe("secondary");
    expect(actionVariant("failed")).toBe("destructive");
  });
});
