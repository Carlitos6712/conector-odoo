import { hintsFor, issuesForRule, type Hint } from "@/features/mappings/hints";
import { mappingDocFixture } from "@/features/mappings/fixtures";
import { stateFromDefinition } from "@/features/mappings/model";
import type { Issue } from "@/features/mappings/types";
import type { FieldSpec } from "@/features/resources/types";

const field = (name: string, type: string, extra: Partial<FieldSpec> = {}): FieldSpec => ({
  name,
  type,
  required: false,
  readonly: false,
  label: null,
  choices: null,
  relation: null,
  ...extra,
});

const direct = (source: string) => ({ type: "direct" as const, source, default: null });
const rule = (target: string, expr: ReturnType<typeof direct> | object) =>
  ({ target, required: false, expr }) as never;

function hints(rules: unknown[], source?: FieldSpec[], target?: FieldSpec[]): Hint[] {
  const state = stateFromDefinition(mappingDocFixture({ rules: rules as never }));
  return hintsFor(state, { sourceFields: source, targetFields: target });
}

const codes = (found: Hint[]) => found.map((h) => `${h.code}@${h.path}`);

describe("hintsFor", () => {
  it("accepts a clean mapping", () => {
    expect(
      hints([rule("name", direct("name"))], [field("name", "string")], [field("name", "string")]),
    ).toEqual([]);
  });

  it("flags empty, malformed and duplicated targets", () => {
    const found = hints([
      rule("", direct("a")),
      rule("a..b", direct("a")),
      rule("x", direct("a")),
      rule("x", direct("a")),
    ]);
    expect(codes(found)).toEqual([
      "targetEmpty@rules[0].target",
      "targetInvalid@rules[1].target",
      "targetDuplicate@rules[3].target",
    ]);
    expect(found.every((h) => h.severity === "error")).toBe(true);
  });

  it("flags a nested target that collides with its parent", () => {
    expect(codes(hints([rule("address", direct("a")), rule("address.city", direct("b"))]))).toEqual(
      ["targetConflict@rules[1].target"],
    );
  });

  it("flags unknown and read-only target fields when the schema is known", () => {
    const target = [field("id", "integer", { readonly: true })];
    expect(
      codes(hints([rule("nope", direct("a")), rule("id", direct("a"))], undefined, target)),
    ).toEqual(["targetUnknown@rules[0].target", "targetReadonly@rules[1].target"]);
    expect(codes(hints([rule("nope", direct("a"))]))).toEqual([]);
  });

  it("warns about required target fields without a rule", () => {
    const target = [
      field("name", "string", { required: true }),
      field("vat", "string", { required: true }),
      field("id", "integer", { required: true, readonly: true }),
    ];
    const found = hints([rule("name", direct("a"))], undefined, target);
    expect(found).toEqual([
      expect.objectContaining({
        code: "requiredUnmapped",
        path: "target.vat",
        params: { field: "vat" },
      }),
    ]);
  });

  it("flags empty and unknown source fields", () => {
    const source = [field("name", "string")];
    expect(
      codes(
        hints(
          [rule("a", direct("")), rule("b", direct("ghost.deep")), rule("c", direct("name.x"))],
          source,
        ),
      ),
    ).toEqual(["sourceEmpty@rules[0].expr.source", "sourceUnknown@rules[1].expr.source"]);
  });

  it("reports step parameters at the same path as the backend", () => {
    const expr = {
      type: "transform",
      input: direct("a"),
      steps: [
        { type: "trim" },
        { type: "to_cents", factor: 0 },
        { type: "date_format", in_format: " ", out_format: "iso" },
        { type: "lookup", table: {}, on_missing: "error", default: null },
        { type: "substring", start: 3, end: 1 },
        { type: "coalesce", alternatives: [direct("")] },
      ],
    };
    expect(codes(hints([rule("t", expr)]))).toEqual([
      "factorInvalid@rules[0].expr.steps[1].factor",
      "formatEmpty@rules[0].expr.steps[2].in_format",
      "lookupEmpty@rules[0].expr.steps[3].table",
      "substringRange@rules[0].expr.steps[4]",
      "sourceEmpty@rules[0].expr.steps[5].alternatives[0].source",
    ]);
  });

  it("warns about a lookup that falls back to an empty default", () => {
    const expr = {
      type: "transform",
      input: direct("a"),
      steps: [{ type: "lookup", table: { a: 1 }, on_missing: "default", default: null }],
    };
    expect(codes(hints([rule("t", expr)]))).toEqual(["lookupDefaultEmpty@rules[0].expr.steps[0]"]);
  });

  it("flags non-integer numeric fields typed by hand", () => {
    const state = stateFromDefinition(
      mappingDocFixture({
        rules: [
          rule("t", {
            type: "transform",
            input: direct("a"),
            steps: [{ type: "to_cents", factor: 100 }],
          }),
        ] as never,
      }),
    );
    const step = (state.rules[0]!.expr as { steps: { factor: string }[] }).steps[0]!;
    step.factor = "1.5";
    expect(codes(hintsFor(state, {}))).toEqual(["factorInvalid@rules[0].expr.steps[0].factor"]);
  });

  it("hints type mismatches between a direct source and its target", () => {
    const source = [field("qty", "string"), field("age", "integer"), field("when", "string")];
    const target = [
      field("qty", "integer"),
      field("age", "number"),
      field("when", "datetime"),
      field("any", "object"),
    ];
    const found = hints(
      [
        rule("qty", direct("qty")),
        rule("age", direct("age")),
        rule("when", direct("when")),
        rule("any", direct("qty")),
      ],
      source,
      target,
    );
    expect(found).toEqual([
      expect.objectContaining({
        code: "typeMismatch",
        severity: "warning",
        path: "rules[0].target",
        params: { produced: "string", expected: "integer" },
      }),
    ]);
  });

  it("follows the output type through steps like the backend", () => {
    const target = [field("n", "integer")];
    const toInt = { type: "transform", input: direct("a"), steps: [{ type: "to_int" }] };
    const upper = { type: "transform", input: direct("a"), steps: [{ type: "upper" }] };
    expect(hints([rule("n", toInt)], [field("a", "string")], target)).toEqual([]);
    expect(codes(hints([rule("n", upper)], [field("a", "string")], target))).toEqual([
      "typeMismatch@rules[0].target",
    ]);
    expect(codes(hints([rule("n", { type: "constant", value: "x" })], undefined, target))).toEqual([
      "typeMismatch@rules[0].target",
    ]);
    expect(hints([rule("n", { type: "constant", value: 3 })], undefined, target)).toEqual([]);
  });
});

describe("issuesForRule", () => {
  const issues: Issue[] = [
    { path: "rules[1].target", severity: "error", message: "a" },
    { path: "rules[1].expr.steps[0].factor", severity: "error", message: "b" },
    { path: "rules[10].target", severity: "error", message: "c" },
    { path: "rules[1]", severity: "warning", message: "d" },
    { path: "target.name", severity: "error", message: "e" },
  ];

  it("selects the findings that live under one rule and not its prefix neighbours", () => {
    expect(issuesForRule(issues, 1).map((i) => i.message)).toEqual(["a", "b", "d"]);
    expect(issuesForRule(issues, 10).map((i) => i.message)).toEqual(["c"]);
    expect(issuesForRule(issues, 2)).toEqual([]);
  });
});
