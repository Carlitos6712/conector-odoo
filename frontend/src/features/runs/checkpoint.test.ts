import { describeCheckpoint } from "@/features/runs/checkpoint";

describe("describeCheckpoint", () => {
  it("is empty for a run that has not saved progress", () => {
    expect(describeCheckpoint({})).toBeNull();
  });

  it("reads the pass, the last processed record and the newest update seen", () => {
    expect(
      describeCheckpoint({
        pass: "reverse",
        last_id: "c-100",
        done: false,
        max_updated_at: "2026-03-01T09:00:00+00:00",
      }),
    ).toEqual({
      pass: "reverse",
      lastId: "c-100",
      done: false,
      maxUpdatedAt: "2026-03-01T09:00:00+00:00",
    });
  });

  it("accepts a numeric last id and ignores unknown or mistyped keys", () => {
    expect(describeCheckpoint({ pass: "forward", last_id: 42, extra: { x: 1 } })).toEqual({
      pass: "forward",
      lastId: "42",
      done: false,
      maxUpdatedAt: null,
    });
    expect(describeCheckpoint({ pass: 3, last_id: { a: 1 } })).toBeNull();
  });
});
