import type { DryRunReport, MappingDoc, StoredMapping } from "@/features/mappings/types";

/** Test fixtures shared by the mappings suites (never imported by app code). */
export function mappingDocFixture(overrides: Partial<MappingDoc> = {}): MappingDoc {
  return {
    schema_version: 1,
    name: "clients-to-partner",
    source_resource: "clients",
    target_resource: "res.partner",
    rules: [
      { target: "name", required: true, expr: { type: "direct", source: "name", default: null } },
      {
        target: "email",
        required: false,
        expr: {
          type: "transform",
          input: { type: "direct", source: "email", default: null },
          steps: [{ type: "trim" }, { type: "lower" }],
        },
      },
    ],
    ...overrides,
  };
}

export function storedMappingFixture(overrides: Partial<StoredMapping> = {}): StoredMapping {
  return {
    name: "clients-to-partner",
    version: 1,
    created_at: "2026-01-02T10:00:00Z",
    definition: mappingDocFixture(),
    ...overrides,
  };
}

export const dryRunFixture: DryRunReport = {
  items: [
    {
      source_id: "u-1",
      ok: true,
      mapped_fields: { name: "Acme" },
      errors: [],
      validation: [],
    },
    {
      source_id: "u-2",
      ok: false,
      mapped_fields: {},
      errors: [{ rule_target: "name", step_index: null, message: "no value" }],
      validation: [],
    },
  ],
  total: 2,
  ok: 1,
  with_errors: 1,
  definition_issues: [],
};
