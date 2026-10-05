import { formatDuration, runDurationSeconds } from "@/features/runs/format";
import { runFixture } from "@/features/jobs/fixtures";

describe("formatDuration", () => {
  it("shows a dash when there is no duration", () => {
    expect(formatDuration(null)).toBe("—");
  });

  it("shows sub-second runs without pretending to be exact", () => {
    expect(formatDuration(0)).toBe("<1 s");
    expect(formatDuration(0.4)).toBe("<1 s");
  });

  it("formats seconds, minutes and hours compactly", () => {
    expect(formatDuration(5)).toBe("5 s");
    expect(formatDuration(65)).toBe("1 min 5 s");
    expect(formatDuration(120)).toBe("2 min");
    expect(formatDuration(3720)).toBe("1 h 2 min");
    expect(formatDuration(7200)).toBe("2 h");
  });

  it("rounds to the nearest second and ignores negative clock skew", () => {
    expect(formatDuration(59.6)).toBe("1 min");
    expect(formatDuration(-3)).toBe("<1 s");
  });
});

describe("runDurationSeconds", () => {
  it("uses the duration the API reports for a finished run", () => {
    expect(runDurationSeconds(runFixture({ duration_seconds: 12 }), Date.now())).toBe(12);
  });

  it("measures a running run against the clock", () => {
    const run = runFixture({
      status: "running",
      finished_at: null,
      duration_seconds: null,
      started_at: "2026-03-01T10:00:00Z",
    });
    expect(runDurationSeconds(run, Date.parse("2026-03-01T10:01:30Z"))).toBe(90);
  });

  it("is unknown when the start time cannot be parsed", () => {
    const run = runFixture({ duration_seconds: null, finished_at: null, started_at: "nope" });
    expect(runDurationSeconds(run, 0)).toBeNull();
  });
});
