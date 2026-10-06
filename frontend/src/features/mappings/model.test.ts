import { mappingDocFixture } from "@/features/mappings/fixtures";
import {
  changeExprKind,
  definitionFromState,
  defaultExpr,
  defaultStep,
  describeExpr,
  formatLiteral,
  mergeSuggestion,
  moveItem,
  newRule,
  parseLiteral,
  removeAt,
  replaceAt,
  stateFromDefinition,
  STEP_TYPES,
} from "@/features/mappings/model";
import type { MappingDoc, StepDoc } from "@/features/mappings/types";

/** Every step type the codec accepts, with non-default params, as the API would return it. */
const allSteps: StepDoc[] = [
  { type: "trim" },
  { type: "upper" },
  { type: "lower" },
  { type: "title" },
  { type: "to_string" },
  { type: "to_number" },
  { type: "to_int" },
  { type: "to_bool" },
  { type: "replace", old: "-", new: "_" },
  { type: "default", value: "n/a" },
  { type: "date_format", in_format: "%d/%m/%Y", out_format: "iso" },
  { type: "to_cents", factor: 1000 },
  { type: "from_cents", factor: 100, as_string: false },
  {
    type: "lookup",
    table: { ES: "Spain", FR: 33, ON: true },
    on_missing: "default",
    default: "other",
  },
  {
    type: "coalesce",
    alternatives: [
      { type: "direct", source: "alt.name", default: null },
      { type: "constant", value: "anon" },
    ],
  },
  { type: "substring", start: 2, end: null },
  { type: "substring", start: 0, end: 5 },
];

const fullDoc: MappingDoc = {
  schema_version: 1,
  name: "everything",
  source_resource: "clients",
  target_resource: "res.partner",
  rules: [
    { target: "name", required: true, expr: { type: "direct", source: "a.b", default: "x" } },
    { target: "address.city", required: false, expr: { type: "constant", value: 42 } },
    {
      target: "ref",
      required: false,
      expr: {
        type: "concat",
        parts: [
          { type: "direct", source: "code", default: null },
          { type: "constant", value: "" },
          { type: "constant", value: null },
          { type: "constant", value: true },
        ],
        separator: " - ",
        skip_empty: false,
      },
    },
    {
      target: "chain",
      required: false,
      expr: {
        type: "transform",
        input: { type: "direct", source: "raw", default: null },
        steps: allSteps,
      },
    },
  ],
};

describe("literals", () => {
  it("parses typed values and keeps everything else as text", () => {
    expect(parseLiteral("")).toBeNull();
    expect(parseLiteral("null")).toBeNull();
    expect(parseLiteral("true")).toBe(true);
    expect(parseLiteral("false")).toBe(false);
    expect(parseLiteral("42")).toBe(42);
    expect(parseLiteral("-1.5")).toBe(-1.5);
    expect(parseLiteral('"42"')).toBe("42");
    expect(parseLiteral('""')).toBe("");
    expect(parseLiteral("hello world")).toBe("hello world");
    expect(parseLiteral("[1, 2]")).toEqual([1, 2]);
    expect(parseLiteral("{bad")).toBe("{bad");
    expect(parseLiteral('"unterminated')).toBe('"unterminated');
  });

  it("formats values so that parsing gives them back", () => {
    for (const value of [
      null,
      "",
      "42",
      "true",
      "null",
      "plain",
      " padded ",
      7,
      1.5,
      false,
      [1],
      { a: 1 },
    ]) {
      expect(parseLiteral(formatLiteral(value))).toEqual(value);
    }
    expect(formatLiteral(null)).toBe("");
    expect(formatLiteral("plain")).toBe("plain");
    expect(formatLiteral("42")).toBe('"42"');
  });
});

describe("definition <-> state", () => {
  it("round-trips a definition that uses every expression and step", () => {
    const state = stateFromDefinition(fullDoc);
    expect(definitionFromState(state)).toEqual(fullDoc);
  });

  it("round-trips the backend fixture and keeps rule order", () => {
    const doc = mappingDocFixture();
    const state = stateFromDefinition(doc);
    expect(state.rules.map((r) => r.target)).toEqual(["name", "email"]);
    expect(definitionFromState(state)).toEqual(doc);
  });

  it("gives every rule a distinct key", () => {
    const keys = stateFromDefinition(fullDoc).rules.map((r) => r.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("serialises typed literals from their text", () => {
    const state = stateFromDefinition(mappingDocFixture({ rules: [] }));
    const rule = newRule();
    const next = {
      ...state,
      rules: [{ ...rule, target: "n", expr: { type: "constant" as const, value: "12" } }],
    };
    expect(definitionFromState(next).rules[0]?.expr).toEqual({ type: "constant", value: 12 });
  });

  it("keeps the schema version and drops client-only keys", () => {
    const out = definitionFromState(stateFromDefinition(fullDoc));
    expect(out.schema_version).toBe(1);
    expect(JSON.stringify(out)).not.toContain("key");
  });
});

describe("list operations", () => {
  it("moves an item one position and stays inside the list", () => {
    expect(moveItem([1, 2, 3], 1, -1)).toEqual([2, 1, 3]);
    expect(moveItem([1, 2, 3], 1, 1)).toEqual([1, 3, 2]);
    expect(moveItem([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
    expect(moveItem([1, 2, 3], 2, 1)).toEqual([1, 2, 3]);
  });

  it("never mutates its input", () => {
    const list = Object.freeze([1, 2, 3]) as number[];
    expect(removeAt(list, 1)).toEqual([1, 3]);
    expect(replaceAt(list, 0, 9)).toEqual([9, 2, 3]);
    expect(moveItem(list, 0, 1)).toEqual([2, 1, 3]);
    expect(list).toEqual([1, 2, 3]);
  });
});

describe("expression helpers", () => {
  it("builds a default for every step type", () => {
    for (const type of STEP_TYPES) expect(defaultStep(type).type).toBe(type);
    expect(STEP_TYPES).toHaveLength(16);
  });

  it("builds a default for every expression kind", () => {
    expect(defaultExpr("direct")).toEqual({ type: "direct", source: "", default: "" });
    expect(defaultExpr("transform")).toMatchObject({ type: "transform", steps: [] });
    expect(defaultExpr("concat")).toMatchObject({ type: "concat", skipEmpty: true, separator: "" });
  });

  it("keeps the source when wrapping a direct in a transform and back", () => {
    const direct = { type: "direct" as const, source: "email", default: "" };
    const wrapped = changeExprKind(direct, "transform");
    expect(wrapped).toEqual({ type: "transform", input: direct, steps: [] });
    expect(changeExprKind(wrapped, "direct")).toEqual(direct);
    expect(changeExprKind(direct, "direct")).toBe(direct);
    expect(changeExprKind(direct, "constant")).toEqual({ type: "constant", value: "" });
  });

  it("describes expressions compactly", () => {
    const state = stateFromDefinition(fullDoc);
    const text = state.rules.map((r) => describeExpr(r.expr));
    expect(text[0]).toBe("a.b");
    expect(text[1]).toBe("42");
    expect(text[2]).toContain("code");
    expect(text[3]).toMatch(/^raw \| trim \| upper/);
  });
});

describe("mergeSuggestion", () => {
  it("adds suggested rules for targets not yet mapped and never overwrites", () => {
    const current = stateFromDefinition(mappingDocFixture());
    const suggested = stateFromDefinition(
      mappingDocFixture({
        rules: [
          {
            target: "name",
            required: false,
            expr: { type: "direct", source: "other", default: null },
          },
          {
            target: "phone",
            required: false,
            expr: { type: "direct", source: "tel", default: null },
          },
        ],
      }),
    );
    const { state, added } = mergeSuggestion(current, suggested);
    expect(added).toBe(1);
    expect(state.rules.map((r) => r.target)).toEqual(["name", "email", "phone"]);
    expect(describeExpr(state.rules[0]!.expr)).toBe("name");
    expect(new Set(state.rules.map((r) => r.key)).size).toBe(3);
  });
});
