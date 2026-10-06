/**
 * Wire shapes of `/admin/api/mappings`. The definition follows the versioned JSON of
 * `domain/mapping_codec.py`: every node carries a `type` discriminator and the codec always
 * writes every field, so a definition read from the API round-trips unchanged.
 */
export type LookupMissing = "error" | "passthrough" | "default";

export const SIMPLE_STEP_TYPES = [
  "trim",
  "upper",
  "lower",
  "title",
  "to_string",
  "to_number",
  "to_int",
  "to_bool",
] as const;
export type SimpleStepType = (typeof SIMPLE_STEP_TYPES)[number];

export type ExprDoc =
  | { type: "direct"; source: string; default: unknown }
  | { type: "constant"; value: unknown }
  | { type: "concat"; parts: ExprDoc[]; separator: string; skip_empty: boolean }
  | { type: "transform"; input: ExprDoc; steps: StepDoc[] };

export type StepDoc =
  | { type: SimpleStepType }
  | { type: "replace"; old: string; new: string }
  | { type: "default"; value: unknown }
  | { type: "date_format"; in_format: string; out_format: string }
  | { type: "to_cents"; factor: number }
  | { type: "from_cents"; factor: number; as_string: boolean }
  | { type: "lookup"; table: Record<string, unknown>; on_missing: LookupMissing; default: unknown }
  | { type: "coalesce"; alternatives: ExprDoc[] }
  | { type: "substring"; start: number; end: number | null };

export interface RuleDoc {
  target: string;
  expr: ExprDoc;
  required: boolean;
}

export interface MappingDoc {
  schema_version: number;
  name: string;
  source_resource: string;
  target_resource: string;
  rules: RuleDoc[];
}

export interface StoredMapping {
  name: string;
  version: number;
  created_at: string;
  definition: MappingDoc;
}

export type Severity = "error" | "warning";

/** A finding anchored at a path such as `rules[2].expr.steps[1].factor` or `target.name`. */
export interface Issue {
  path: string;
  severity: Severity;
  message: string;
}

export interface SaveResult {
  mapping: StoredMapping;
  /** False when the definition equals the latest version and nothing was stored. */
  created: boolean;
  warnings: Issue[];
}

export interface RuleError {
  rule_target: string;
  step_index: number | null;
  message: string;
}

export interface DryRunItem {
  source_id: string | null;
  ok: boolean;
  mapped_fields: Record<string, unknown>;
  errors: RuleError[];
  validation: Issue[];
}

export interface DryRunReport {
  items: DryRunItem[];
  total: number;
  ok: number;
  with_errors: number;
  definition_issues: Issue[];
}

export interface DryRunResult {
  report: DryRunReport;
  /** Source record fields by id, fetched with a preview (the report does not carry them). */
  inputs: Record<string, Record<string, unknown>>;
}

export interface Suggestion {
  definition: MappingDoc;
  unmatched_source: string[];
  unmatched_target: string[];
}
