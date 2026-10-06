/**
 * Client-side hints for a mapping being edited. They mirror `domain/mapping_validation.py` so
 * the author sees problems before saving, and they use the same paths (`rules[1].target`,
 * `rules[0].expr.steps[2].factor`, `target.<field>`), so hints and server findings can be shown
 * on the same rule. The server stays the authority: it validates again on save.
 */
import {
  parseLiteral,
  type EditorState,
  type FExpr,
  type FStep,
  type LookupRow,
} from "@/features/mappings/model";
import type { Issue, Severity } from "@/features/mappings/types";
import type { FieldSpec } from "@/features/resources/types";

export interface Hint {
  path: string;
  severity: Severity;
  /** Translation key suffix under `mappings.hints.`. */
  code: string;
  params?: Record<string, string>;
}

export interface HintContext {
  /** Known fields of each side; `undefined` when the schema is not loaded (checks are skipped). */
  sourceFields?: readonly FieldSpec[];
  targetFields?: readonly FieldSpec[];
}

const UNCHECKED_TARGETS = new Set(["unknown", "object", "array"]);
const FITS = new Set(["integer>number", "string>date", "string>datetime", "date>datetime"]);
const isInteger = (text: string) => /^\s*-?\d+\s*$/.test(text);

function typeOfLiteral(value: unknown): string | null {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  if (typeof value === "string") return "string";
  if (Array.isArray(value)) return "array";
  return value !== null && typeof value === "object" ? "object" : null;
}

function stepType(step: FStep): string | null {
  switch (step.type) {
    case "to_number":
      return "number";
    case "to_int":
    case "to_cents":
      return "integer";
    case "to_bool":
      return "boolean";
    case "from_cents":
      return step.asString ? "string" : "number";
    case "lookup":
      return null;
    default:
      return "string";
  }
}

/** The type a rule produces, when it can be known (same rules as the server). */
function outputType(expr: FExpr, source: readonly FieldSpec[] | undefined): string | null {
  switch (expr.type) {
    case "direct": {
      const spec = source?.find((field) => field.name === expr.source);
      return !spec || spec.type === "unknown" ? null : spec.type;
    }
    case "constant":
      return typeOfLiteral(parseLiteral(expr.value));
    case "concat":
      return "string";
    case "transform": {
      const last = [...expr.steps]
        .reverse()
        .find((s) => s.type !== "default" && s.type !== "coalesce");
      return last ? stepType(last) : outputType(expr.input, source);
    }
  }
}

function hintsForExpr(expr: FExpr, path: string, ctx: HintContext, out: Hint[]): void {
  switch (expr.type) {
    case "direct": {
      if (expr.source.trim() === "") {
        out.push({ path: `${path}.source`, severity: "error", code: "sourceEmpty" });
      } else if (ctx.sourceFields) {
        const root = expr.source.split(".")[0];
        if (!ctx.sourceFields.some((field) => field.name === root)) {
          out.push({
            path: `${path}.source`,
            severity: "warning",
            code: "sourceUnknown",
            params: { field: root ?? "" },
          });
        }
      }
      return;
    }
    case "concat":
      if (expr.parts.length === 0) out.push({ path, severity: "warning", code: "concatEmpty" });
      expr.parts.forEach((part, k) => hintsForExpr(part, `${path}.parts[${k}]`, ctx, out));
      return;
    case "transform":
      hintsForExpr(expr.input, `${path}.input`, ctx, out);
      expr.steps.forEach((step, j) => hintsForStep(step, `${path}.steps[${j}]`, ctx, out));
      return;
    case "constant":
      return;
  }
}

const filled = (rows: readonly LookupRow[]) => rows.filter((r) => r.from !== "" || r.to !== "");

function hintsForStep(step: FStep, path: string, ctx: HintContext, out: Hint[]): void {
  switch (step.type) {
    case "to_cents":
    case "from_cents":
      if (!isInteger(step.factor) || Number(step.factor) < 1) {
        out.push({ path: `${path}.factor`, severity: "error", code: "factorInvalid" });
      }
      return;
    case "date_format":
      for (const [field, value] of [
        ["in_format", step.inFormat],
        ["out_format", step.outFormat],
      ] as const) {
        if (value.trim() === "") {
          out.push({ path: `${path}.${field}`, severity: "error", code: "formatEmpty" });
        }
      }
      return;
    case "lookup":
      if (filled(step.rows).length === 0) {
        out.push({ path: `${path}.table`, severity: "warning", code: "lookupEmpty" });
      }
      if (step.onMissing === "default" && step.default === "") {
        out.push({ path, severity: "warning", code: "lookupDefaultEmpty" });
      }
      return;
    case "substring": {
      const endBlank = step.end.trim() === "";
      if (!isInteger(step.start)) {
        out.push({ path: `${path}.start`, severity: "error", code: "substringInvalid" });
      }
      if (!endBlank && !isInteger(step.end)) {
        out.push({ path: `${path}.end`, severity: "error", code: "substringInvalid" });
      } else if (!endBlank && isInteger(step.start) && Number(step.end) <= Number(step.start)) {
        out.push({ path, severity: "error", code: "substringRange" });
      }
      return;
    }
    case "coalesce":
      step.alternatives.forEach((alt, k) =>
        hintsForExpr(alt, `${path}.alternatives[${k}]`, ctx, out),
      );
      return;
    default:
      return;
  }
}

export function hintsFor(state: EditorState, ctx: HintContext): Hint[] {
  const out: Hint[] = [];
  const seen: string[] = [];
  state.rules.forEach((rule, index) => {
    const path = `rules[${index}]`;
    const targetPath = `${path}.target`;
    const { target } = rule;
    const parts = target.split(".");
    if (target === "") {
      out.push({ path: targetPath, severity: "error", code: "targetEmpty" });
    } else if (parts.some((part) => part === "" || part !== part.trim())) {
      out.push({ path: targetPath, severity: "error", code: "targetInvalid" });
    } else {
      const clash = seen.find(
        (other) =>
          other === target || other.startsWith(`${target}.`) || target.startsWith(`${other}.`),
      );
      if (clash === target) {
        out.push({ path: targetPath, severity: "error", code: "targetDuplicate" });
      } else if (clash !== undefined) {
        out.push({
          path: targetPath,
          severity: "error",
          code: "targetConflict",
          params: { other: clash },
        });
      } else {
        seen.push(target);
        const spec = ctx.targetFields?.find((field) => field.name === parts[0]);
        if (ctx.targetFields && !spec) {
          out.push({
            path: targetPath,
            severity: "error",
            code: "targetUnknown",
            params: { field: parts[0] ?? "" },
          });
        } else if (spec?.readonly) {
          out.push({
            path: targetPath,
            severity: "warning",
            code: "targetReadonly",
            params: { field: spec.name },
          });
        }
        if (spec && parts.length === 1 && !UNCHECKED_TARGETS.has(spec.type)) {
          const produced = outputType(rule.expr, ctx.sourceFields);
          if (
            produced !== null &&
            produced !== spec.type &&
            !FITS.has(`${produced}>${spec.type}`)
          ) {
            out.push({
              path: targetPath,
              severity: "warning",
              code: "typeMismatch",
              params: { produced, expected: spec.type },
            });
          }
        }
      }
    }
    hintsForExpr(rule.expr, `${path}.expr`, ctx, out);
  });

  if (ctx.targetFields) {
    const covered = new Set(state.rules.map((rule) => rule.target.split(".")[0]));
    for (const spec of ctx.targetFields) {
      if (spec.required && !spec.readonly && !covered.has(spec.name)) {
        out.push({
          path: `target.${spec.name}`,
          severity: "warning",
          code: "requiredUnmapped",
          params: { field: spec.name },
        });
      }
    }
  }
  return out;
}

/** The findings that live under rule `index` (`rules[1]` does not match `rules[10]`). */
export function issuesForRule<T extends { path: string }>(
  issues: readonly T[],
  index: number,
): T[] {
  const base = `rules[${index}]`;
  return issues.filter(
    (issue) =>
      issue.path === base || issue.path.startsWith(`${base}.`) || issue.path.startsWith(`${base}[`),
  );
}

export const hintToIssue = (hint: Hint, message: string): Issue => ({
  path: hint.path,
  severity: hint.severity,
  message,
});
