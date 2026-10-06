/**
 * Editor state model for mappings: pure functions, no React, no I/O.
 *
 * The API definition (`MappingDoc`, see `domain/mapping_codec.py`) is converted to a form state
 * where every value the user types is text (numbers and literals are parsed when the definition
 * is rebuilt), rules carry a stable `key` for React lists, and lookup tables are ordered rows.
 * `definitionFromState(stateFromDefinition(doc))` gives `doc` back.
 */
import {
  SIMPLE_STEP_TYPES,
  type ExprDoc,
  type LookupMissing,
  type MappingDoc,
  type RuleDoc,
  type SimpleStepType,
  type StepDoc,
} from "@/features/mappings/types";

export const SCHEMA_VERSION = 1;

// -- literals ----------------------------------------------------------------------------------

const NUMBER = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/;

/**
 * Text typed into a "value" input -> JSON value. Empty and `null` are null; `true`/`false` and
 * numbers are typed; `"..."`, `[...]` and `{...}` are parsed as JSON when they are valid;
 * anything else is the text itself. Quote a value (`"42"`) to force text.
 */
export function parseLiteral(text: string): unknown {
  if (text === "") return null;
  const trimmed = text.trim();
  if (trimmed === "null") return null;
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (NUMBER.test(trimmed)) {
    const number = Number(trimmed);
    if (Number.isFinite(number)) return number;
  }
  if (/^["[{]/.test(trimmed)) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (typeof parsed === "string" || (parsed !== null && typeof parsed === "object")) {
        return parsed;
      }
    } catch {
      // Not JSON: keep the text.
    }
  }
  return text;
}

/** JSON value -> the text that `parseLiteral` turns back into the same value. */
export function formatLiteral(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") {
    return parseLiteral(value) === value ? value : JSON.stringify(value);
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

const toInteger = (text: string): number => (/^\s*-?\d+\s*$/.test(text) ? Number(text) : NaN);

// -- state -------------------------------------------------------------------------------------

export interface LookupRow {
  from: string;
  /** Literal text (see `parseLiteral`). */
  to: string;
}

export type FExpr =
  | { type: "direct"; source: string; default: string }
  | { type: "constant"; value: string }
  | { type: "concat"; parts: FExpr[]; separator: string; skipEmpty: boolean }
  | { type: "transform"; input: FExpr; steps: FStep[] };

export type FStep =
  | { type: SimpleStepType }
  | { type: "replace"; old: string; new: string }
  | { type: "default"; value: string }
  | { type: "date_format"; inFormat: string; outFormat: string }
  | { type: "to_cents"; factor: string }
  | { type: "from_cents"; factor: string; asString: boolean }
  | { type: "lookup"; rows: LookupRow[]; onMissing: LookupMissing; default: string }
  | { type: "coalesce"; alternatives: FExpr[] }
  | { type: "substring"; start: string; end: string };

export interface FRule {
  /** Client-only identity for React lists; never sent to the API. */
  key: string;
  target: string;
  required: boolean;
  expr: FExpr;
}

export interface EditorState {
  name: string;
  sourceResource: string;
  targetResource: string;
  rules: FRule[];
}

export type ExprKind = FExpr["type"];
export type StepType = FStep["type"];

export const EXPR_KINDS: readonly ExprKind[] = ["direct", "constant", "concat", "transform"];
export const STEP_TYPES: readonly StepType[] = [
  ...SIMPLE_STEP_TYPES,
  "replace",
  "default",
  "date_format",
  "to_cents",
  "from_cents",
  "lookup",
  "coalesce",
  "substring",
];

let keySeed = 0;
const nextKey = () => `rule-${++keySeed}`;

export const emptyState = (): EditorState => ({
  name: "",
  sourceResource: "",
  targetResource: "",
  rules: [],
});

export function defaultExpr(kind: ExprKind): FExpr {
  switch (kind) {
    case "direct":
      return { type: "direct", source: "", default: "" };
    case "constant":
      return { type: "constant", value: "" };
    case "concat":
      return { type: "concat", parts: [], separator: "", skipEmpty: true };
    case "transform":
      return { type: "transform", input: defaultExpr("direct"), steps: [] };
  }
}

export function defaultStep(type: StepType): FStep {
  switch (type) {
    case "replace":
      return { type, old: "", new: "" };
    case "default":
      return { type, value: "" };
    case "date_format":
      return { type, inFormat: "iso", outFormat: "iso" };
    case "to_cents":
      return { type, factor: "100" };
    case "from_cents":
      return { type, factor: "100", asString: true };
    case "lookup":
      return { type, rows: [], onMissing: "error", default: "" };
    case "coalesce":
      return { type, alternatives: [] };
    case "substring":
      return { type, start: "0", end: "" };
    default:
      return { type };
  }
}

export function newRule(target = ""): FRule {
  return { key: nextKey(), target, required: false, expr: defaultExpr("direct") };
}

/**
 * Switches an expression to another kind keeping what can be kept: a direct wrapped in a
 * transform stays as its input, and unwrapping a transform gives its input back.
 */
export function changeExprKind(expr: FExpr, kind: ExprKind): FExpr {
  if (expr.type === kind) return expr;
  if (kind === "transform") return { type: "transform", input: expr, steps: [] };
  if (expr.type === "transform" && expr.input.type === kind) return expr.input;
  return defaultExpr(kind);
}

// -- list operations (immutable) ---------------------------------------------------------------

export function moveItem<T>(list: readonly T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) return [...list];
  const copy = [...list];
  const [item] = copy.splice(index, 1);
  copy.splice(target, 0, item as T);
  return copy;
}

export const removeAt = <T>(list: readonly T[], index: number): T[] =>
  list.filter((_, i) => i !== index);

export const replaceAt = <T>(list: readonly T[], index: number, value: T): T[] =>
  list.map((item, i) => (i === index ? value : item));

// -- definition -> state -----------------------------------------------------------------------

function exprFromDoc(doc: ExprDoc): FExpr {
  switch (doc.type) {
    case "direct":
      return { type: "direct", source: doc.source, default: formatLiteral(doc.default) };
    case "constant":
      return { type: "constant", value: formatLiteral(doc.value) };
    case "concat":
      return {
        type: "concat",
        parts: doc.parts.map(exprFromDoc),
        separator: doc.separator,
        skipEmpty: doc.skip_empty,
      };
    case "transform":
      return {
        type: "transform",
        input: exprFromDoc(doc.input),
        steps: doc.steps.map(stepFromDoc),
      };
  }
}

function stepFromDoc(doc: StepDoc): FStep {
  switch (doc.type) {
    case "replace":
      return { type: "replace", old: doc.old, new: doc.new };
    case "default":
      return { type: "default", value: formatLiteral(doc.value) };
    case "date_format":
      return { type: "date_format", inFormat: doc.in_format, outFormat: doc.out_format };
    case "to_cents":
      return { type: "to_cents", factor: String(doc.factor) };
    case "from_cents":
      return { type: "from_cents", factor: String(doc.factor), asString: doc.as_string };
    case "lookup":
      return {
        type: "lookup",
        rows: Object.entries(doc.table).map(([from, to]) => ({ from, to: formatLiteral(to) })),
        onMissing: doc.on_missing,
        default: formatLiteral(doc.default),
      };
    case "coalesce":
      return { type: "coalesce", alternatives: doc.alternatives.map(exprFromDoc) };
    case "substring":
      return {
        type: "substring",
        start: String(doc.start),
        end: doc.end === null ? "" : String(doc.end),
      };
    default:
      return { type: doc.type };
  }
}

export function stateFromDefinition(doc: MappingDoc): EditorState {
  return {
    name: doc.name,
    sourceResource: doc.source_resource,
    targetResource: doc.target_resource,
    rules: doc.rules.map((rule) => ({
      key: nextKey(),
      target: rule.target,
      required: rule.required,
      expr: exprFromDoc(rule.expr),
    })),
  };
}

// -- state -> definition -----------------------------------------------------------------------

function exprToDoc(expr: FExpr): ExprDoc {
  switch (expr.type) {
    case "direct":
      return { type: "direct", source: expr.source, default: parseLiteral(expr.default) };
    case "constant":
      return { type: "constant", value: parseLiteral(expr.value) };
    case "concat":
      return {
        type: "concat",
        parts: expr.parts.map(exprToDoc),
        separator: expr.separator,
        skip_empty: expr.skipEmpty,
      };
    case "transform":
      return { type: "transform", input: exprToDoc(expr.input), steps: expr.steps.map(stepToDoc) };
  }
}

function stepToDoc(step: FStep): StepDoc {
  switch (step.type) {
    case "replace":
      return { type: "replace", old: step.old, new: step.new };
    case "default":
      return { type: "default", value: parseLiteral(step.value) };
    case "date_format":
      return { type: "date_format", in_format: step.inFormat, out_format: step.outFormat };
    case "to_cents":
      return { type: "to_cents", factor: toInteger(step.factor) };
    case "from_cents":
      return { type: "from_cents", factor: toInteger(step.factor), as_string: step.asString };
    case "lookup":
      return {
        type: "lookup",
        // A blank placeholder row (nothing typed on either side) is not part of the table.
        table: Object.fromEntries(
          step.rows
            .filter((row) => row.from !== "" || row.to !== "")
            .map((row) => [row.from, parseLiteral(row.to)]),
        ),
        on_missing: step.onMissing,
        default: parseLiteral(step.default),
      };
    case "coalesce":
      return { type: "coalesce", alternatives: step.alternatives.map(exprToDoc) };
    case "substring":
      return {
        type: "substring",
        start: toInteger(step.start),
        end: step.end.trim() === "" ? null : toInteger(step.end),
      };
    default:
      return { type: step.type };
  }
}

export function definitionFromState(state: EditorState): MappingDoc {
  const rules: RuleDoc[] = state.rules.map((rule) => ({
    target: rule.target,
    expr: exprToDoc(rule.expr),
    required: rule.required,
  }));
  return {
    schema_version: SCHEMA_VERSION,
    name: state.name,
    source_resource: state.sourceResource,
    target_resource: state.targetResource,
    rules,
  };
}

// -- presentation helpers ----------------------------------------------------------------------

/** One-line summary of an expression: `raw | trim | upper`, `a - b`, `"text"`. */
export function describeExpr(expr: FExpr): string {
  switch (expr.type) {
    case "direct":
      return expr.source || "∅";
    case "constant":
      return expr.value === "" ? "null" : expr.value;
    case "concat":
      return expr.parts.map(describeExpr).join(expr.separator ? ` ${expr.separator} ` : " + ");
    case "transform":
      return [describeExpr(expr.input), ...expr.steps.map((step) => step.type)].join(" | ");
  }
}

/**
 * Adds the suggested rules whose target has no rule yet. Existing rules are never touched, and
 * the suggestion never replaces the definition: the caller still has to review and save.
 */
export function mergeSuggestion(
  current: EditorState,
  suggested: EditorState,
): { state: EditorState; added: number } {
  const taken = new Set(current.rules.map((rule) => rule.target));
  const fresh = suggested.rules
    .filter((rule) => !taken.has(rule.target))
    .map((rule) => ({ ...rule, key: nextKey() }));
  return { state: { ...current, rules: [...current.rules, ...fresh] }, added: fresh.length };
}
