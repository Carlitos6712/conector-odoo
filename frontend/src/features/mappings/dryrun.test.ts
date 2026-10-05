import { dryRunIssues } from "@/features/mappings/dryrun";
import { dryRunFixture, mappingDocFixture } from "@/features/mappings/fixtures";
import type { DryRunReport } from "@/features/mappings/types";

const doc = mappingDocFixture();

const report = (overrides: Partial<DryRunReport>): DryRunReport => ({
  ...dryRunFixture,
  items: [],
  ...overrides,
});

describe("dryRunIssues", () => {
  it("anchors a rule error to its rule and a step error to the step", () => {
    const issues = dryRunIssues(
      doc,
      report({
        items: [
          {
            source_id: "u-1",
            ok: false,
            mapped_fields: {},
            errors: [
              { rule_target: "name", step_index: null, message: "no value" },
              { rule_target: "email", step_index: 1, message: "cannot lower" },
            ],
            validation: [],
          },
        ],
      }),
    );
    expect(issues).toEqual([
      { path: "rules[0]", severity: "error", message: "no value" },
      { path: "rules[1].expr.steps[1]", severity: "error", message: "cannot lower" },
    ]);
  });

  it("reports each distinct problem once however many records hit it", () => {
    const item = {
      ok: false,
      mapped_fields: {},
      validation: [],
      errors: [{ rule_target: "name", step_index: null, message: "no value" }],
    };
    const issues = dryRunIssues(
      doc,
      report({
        items: [
          { ...item, source_id: "a" },
          { ...item, source_id: "b" },
        ],
      }),
    );
    expect(issues).toHaveLength(1);
  });

  it("maps value checks (named after the target field) to the rule that sets the field", () => {
    const issues = dryRunIssues(
      doc,
      report({
        items: [
          {
            source_id: "u-1",
            ok: false,
            mapped_fields: {},
            errors: [],
            validation: [
              { path: "email", severity: "error", message: "expected integer, got 'x'" },
              { path: "other", severity: "error", message: "required field has no value" },
            ],
          },
        ],
      }),
    );
    expect(issues).toEqual([
      { path: "rules[1]", severity: "error", message: "expected integer, got 'x'" },
      { path: "target.other", severity: "error", message: "required field has no value" },
    ]);
  });

  it("keeps the definition findings with their own paths and sends nested targets to their rule", () => {
    const nested = mappingDocFixture({
      rules: [
        {
          target: "address.city",
          required: false,
          expr: { type: "direct", source: "city", default: null },
        },
      ],
    });
    const issues = dryRunIssues(
      nested,
      report({
        definition_issues: [
          { path: "rules[0].expr.source", severity: "warning", message: "not in schema" },
        ],
        items: [
          {
            source_id: "u-1",
            ok: false,
            mapped_fields: {},
            errors: [{ rule_target: "address.city", step_index: null, message: "boom" }],
            validation: [{ path: "address", severity: "error", message: "bad" }],
          },
        ],
      }),
    );
    expect(issues.map((i) => i.path)).toEqual(["rules[0].expr.source", "rules[0]", "rules[0]"]);
  });
});
