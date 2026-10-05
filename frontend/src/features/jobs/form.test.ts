import { jobFixture } from "@/features/jobs/fixtures";
import {
  compatibleMappings,
  emptyJobState,
  JOB_STEPS,
  jobToInput,
  mappingMatches,
  stateFromJob,
  stepOfField,
  toJobInput,
  validateAll,
  validateStep,
  type JobFormState,
} from "@/features/jobs/form";
import { mappingDocFixture, storedMappingFixture } from "@/features/mappings/fixtures";

const valid = (overrides: Partial<JobFormState> = {}): JobFormState => ({
  ...emptyJobState(),
  name: "Clientes a Odoo",
  sourceProfileId: "1",
  sourceResource: "clients",
  targetProfileId: "2",
  targetResource: "res.partner",
  mappingName: "clients-to-partner",
  ...overrides,
});

describe("round trip", () => {
  const jobs = {
    manual: jobFixture(),
    scheduled: jobFixture({
      trigger: { kind: "schedule", cron: "30 9 * * 1,3" },
      mapping: { name: "clients-to-partner", version: 3 },
      batch_size: 250,
      enabled: false,
    }),
    webhook: jobFixture({
      trigger: { kind: "webhook", event_types: ["partner.created", "custom.event"] },
    }),
    bidirectional: jobFixture({
      direction: "bidirectional",
      reverse_mapping: { name: "partner-to-clients", version: 2 },
      upsert_key: "field:email",
      conflict_rule: "newest_wins",
      source_updated_field: "updated_at",
      target_updated_field: "write_date",
      record_filter: {
        equals: { active: true, country: "ES", zip: "007", limit: 5 },
        since: "2026-01-01T00:00:00Z",
        raw: { domain: [["a", "=", 1]] },
      },
    }),
  };

  it.each(Object.entries(jobs))("rebuilds the %s job unchanged", (_name, job) => {
    expect(toJobInput(stateFromJob(job))).toEqual(jobToInput(job));
  });

  it("strips server-only fields", () => {
    const input = jobToInput(jobFixture({ next_fire: "2026-01-01T00:00:00Z" }));
    expect(input).not.toHaveProperty("id");
    expect(input).not.toHaveProperty("next_fire");
  });
});

describe("toJobInput", () => {
  it("builds a minimal manual job", () => {
    expect(toJobInput(valid({ name: "  Clientes a Odoo " }))).toEqual({
      name: "Clientes a Odoo",
      source: { profile_id: 1, resource: "clients" },
      target: { profile_id: 2, resource: "res.partner" },
      mapping: { name: "clients-to-partner", version: null },
      reverse_mapping: null,
      direction: "a_to_b",
      trigger: { kind: "manual" },
      record_filter: { equals: {}, since: null, raw: null },
      batch_size: 100,
      upsert_key: "xref",
      conflict_rule: "source_wins",
      source_updated_field: null,
      target_updated_field: null,
      enabled: true,
    });
  });

  it("pins mapping versions when chosen", () => {
    const input = toJobInput(
      valid({
        direction: "bidirectional",
        mappingVersion: "3",
        reverseName: "partner-to-clients",
        reverseVersion: "2",
      }),
    );
    expect(input.mapping).toEqual({ name: "clients-to-partner", version: 3 });
    expect(input.reverse_mapping).toEqual({ name: "partner-to-clients", version: 2 });
  });

  it("drops a stale reverse mapping for a one way job", () => {
    expect(
      toJobInput(valid({ reverseName: "old", reverseVersion: "1" })).reverse_mapping,
    ).toBeNull();
  });

  it("builds a field upsert key and trims it", () => {
    expect(toJobInput(valid({ upsertKind: "field", upsertField: " email " })).upsert_key).toBe(
      "field:email",
    );
  });

  it("types filter values like the mapping editor and drops blank rows", () => {
    const input = toJobInput(
      valid({
        filters: [
          { field: "active", value: "true" },
          { field: "age", value: "42" },
          { field: "zip", value: '"007"' },
          { field: "note", value: "plain text" },
          { field: "", value: "" },
        ],
      }),
    );
    expect(input.record_filter.equals).toEqual({
      active: true,
      age: 42,
      zip: "007",
      note: "plain text",
    });
  });

  it("keeps the updated-at fields only for newest wins", () => {
    const base = { sourceUpdatedField: "updated_at", targetUpdatedField: "write_date" };
    expect(toJobInput(valid({ ...base, conflictRule: "source_wins" })).source_updated_field).toBe(
      null,
    );
    const newest = toJobInput(
      valid({ ...base, conflictRule: "newest_wins", direction: "bidirectional", reverseName: "r" }),
    );
    expect(newest.source_updated_field).toBe("updated_at");
    expect(newest.target_updated_field).toBe("write_date");
  });

  it("falls back to source wins when a one way job keeps a half-filled newest wins", () => {
    const input = toJobInput(valid({ conflictRule: "newest_wins", sourceUpdatedField: "u" }));
    expect(input.conflict_rule).toBe("source_wins");
    expect(input.source_updated_field).toBeNull();
  });

  it("serialises triggers", () => {
    expect(toJobInput(valid({ triggerKind: "schedule", cron: " 0  9 * * * " })).trigger).toEqual({
      kind: "schedule",
      cron: "0 9 * * *",
    });
    expect(
      toJobInput(valid({ triggerKind: "webhook", eventTypes: ["partner.updated"] })).trigger,
    ).toEqual({ kind: "webhook", event_types: ["partner.updated"] });
  });
});

describe("validateStep", () => {
  it("has the five wizard steps in order", () => {
    expect(JOB_STEPS).toEqual(["basics", "endpoints", "options", "trigger", "review"]);
  });

  it("requires a bounded name", () => {
    expect(validateStep("basics", valid({ name: "  " }))).toEqual({
      name: "jobs.errors.nameRequired",
    });
    expect(validateStep("basics", valid({ name: "x".repeat(121) }))).toEqual({
      name: "jobs.errors.nameTooLong",
    });
    expect(validateStep("basics", valid())).toEqual({});
  });

  it("requires both endpoints and a mapping", () => {
    expect(validateStep("endpoints", emptyJobState())).toEqual({
      sourceProfile: "jobs.errors.required",
      sourceResource: "jobs.errors.required",
      targetProfile: "jobs.errors.required",
      targetResource: "jobs.errors.required",
      mapping: "jobs.errors.required",
    });
    expect(validateStep("endpoints", valid())).toEqual({});
  });

  it.each(["b_to_a", "bidirectional"] as const)(
    "requires a reverse mapping for %s",
    (direction) => {
      expect(validateStep("endpoints", valid({ direction }))).toEqual({
        reverseMapping: "jobs.errors.required",
      });
      expect(validateStep("endpoints", valid({ direction, reverseName: "r" }))).toEqual({});
    },
  );

  it("checks the batch size", () => {
    for (const batchSize of ["0", "1001", "abc", "1.5", ""]) {
      expect(validateStep("options", valid({ batchSize }))).toEqual({
        batchSize: "jobs.errors.batchSize",
      });
    }
    expect(validateStep("options", valid({ batchSize: "1000" }))).toEqual({});
  });

  it("needs a field for a field upsert key", () => {
    expect(validateStep("options", valid({ upsertKind: "field", upsertField: " " }))).toEqual({
      upsertField: "jobs.errors.required",
    });
  });

  it("checks the filter rows", () => {
    expect(validateStep("options", valid({ filters: [{ field: "", value: "x" }] }))).toEqual({
      filters: "jobs.errors.filterField",
    });
    expect(
      validateStep(
        "options",
        valid({
          filters: [
            { field: "a", value: "1" },
            { field: "a", value: "2" },
          ],
        }),
      ),
    ).toEqual({ filters: "jobs.errors.filterDuplicate" });
  });

  it("needs updated-at fields on both sides for newest wins", () => {
    expect(
      validateStep(
        "options",
        valid({
          direction: "bidirectional",
          reverseName: "r",
          conflictRule: "newest_wins",
          sourceUpdatedField: "updated_at",
        }),
      ),
    ).toEqual({ targetUpdatedField: "jobs.errors.required" });
  });

  it("ignores the conflict rule on one way jobs", () => {
    expect(validateStep("options", valid({ conflictRule: "newest_wins" }))).toEqual({});
  });

  it("validates cron schedules like the backend", () => {
    expect(validateStep("trigger", valid({ triggerKind: "schedule", cron: "* * *" }))).toEqual({
      cron: "jobs.cron.errors.fields",
    });
    expect(validateStep("trigger", valid({ triggerKind: "schedule", cron: "61 * * * *" }))).toEqual(
      { cron: "jobs.cron.errors.range" },
    );
    expect(validateStep("trigger", valid({ triggerKind: "schedule", cron: "0 9 * * *" }))).toEqual(
      {},
    );
  });

  it("flags a schedule that never fires", () => {
    expect(validateStep("trigger", valid({ triggerKind: "schedule", cron: "0 0 31 2 *" }))).toEqual(
      { cron: "jobs.cron.neverFires" },
    );
  });

  it("needs at least one webhook event type", () => {
    expect(validateStep("trigger", valid({ triggerKind: "webhook", eventTypes: [] }))).toEqual({
      eventTypes: "jobs.errors.eventTypes",
    });
  });

  it("validates everything for the review step", () => {
    expect(validateAll(emptyJobState())).toMatchObject({
      name: "jobs.errors.nameRequired",
      mapping: "jobs.errors.required",
    });
    expect(validateAll(valid())).toEqual({});
  });

  it("maps a field error back to its step", () => {
    expect(stepOfField("name")).toBe("basics");
    expect(stepOfField("reverseMapping")).toBe("endpoints");
    expect(stepOfField("batchSize")).toBe("options");
    expect(stepOfField("cron")).toBe("trigger");
  });
});

describe("mapping compatibility", () => {
  const forward = storedMappingFixture();
  const reverse = storedMappingFixture({
    name: "partner-to-clients",
    definition: mappingDocFixture({
      name: "partner-to-clients",
      source_resource: "res.partner",
      target_resource: "clients",
    }),
  });

  it("matches a mapping to the resource pair", () => {
    expect(mappingMatches(forward.definition, "clients", "res.partner")).toBe(true);
    expect(mappingMatches(forward.definition, "res.partner", "clients")).toBe(false);
  });

  it("keeps only the compatible mappings", () => {
    expect(compatibleMappings([forward, reverse], "clients", "res.partner")).toEqual([forward]);
    expect(compatibleMappings([forward, reverse], "res.partner", "clients")).toEqual([reverse]);
    expect(compatibleMappings([forward, reverse], "", "res.partner")).toEqual([]);
  });
});
