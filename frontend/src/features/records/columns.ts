import type { FieldSpec, RecordSchema, RemoteRecord } from "@/features/records/types";

const PREFERRED = ["name", "email", "vat", "city", "ref"] as const;
const MAX_FALLBACK_COLUMNS = 3;
const NUMBER_TYPES = new Set(["integer", "float", "monetary", "number"]);

const isScalar = (value: unknown): boolean =>
  value === null || value === undefined || ["string", "number", "boolean"].includes(typeof value);

/** Columns of the table: the usual identity fields when present, else the first simple ones. */
export function pickColumns(schema: RecordSchema): FieldSpec[] {
  const preferred = PREFERRED.flatMap((name) => schema.fields.find((f) => f.name === name) ?? []);
  if (preferred.length > 0) return preferred;
  return schema.fields
    .filter((f) => f.name !== schema.id_field && f.relation === null)
    .slice(0, MAX_FALLBACK_COLUMNS);
}

/**
 * Every column the data has: all schema fields but the id (it has its own column), then any key
 * that only appears in the records, in first-seen order.
 */
export function allColumns(schema: RecordSchema, records: readonly RemoteRecord[]): FieldSpec[] {
  const columns = schema.fields.filter((f) => f.name !== schema.id_field);
  const known = new Set(schema.fields.map((f) => f.name));
  for (const record of records) {
    for (const name of Object.keys(record.fields)) {
      if (known.has(name)) continue;
      known.add(name);
      columns.push({
        name,
        type: "unknown",
        required: false,
        readonly: true,
        label: null,
        choices: null,
        relation: null,
      });
    }
  }
  return columns;
}

/** What names a record to a human: its name, then display_name, then `#id`. */
export function recordLabel(record: RemoteRecord): string {
  for (const key of ["name", "display_name"]) {
    const value = record.fields[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return `#${record.id}`;
}

/** Writable fields shown in the edit form; ids, read-only fields and relations stay out. */
export function editableFields(schema: RecordSchema, record: RemoteRecord): FieldSpec[] {
  return schema.fields.filter(
    (f) =>
      !f.readonly &&
      f.name !== schema.id_field &&
      f.relation === null &&
      isScalar(record.fields[f.name]),
  );
}

/** Writable fields offered when creating: no id, no read-only fields, no relations. */
export function creatableFields(schema: RecordSchema): FieldSpec[] {
  return schema.fields.filter(
    (f) => !f.readonly && f.name !== schema.id_field && f.relation === null,
  );
}

export type FormValues = Record<string, string | boolean>;

const textOf = (value: unknown): string =>
  value === null || value === undefined || value === false ? "" : String(value);

export function initialForm(specs: readonly FieldSpec[], record: RemoteRecord): FormValues {
  const form: FormValues = {};
  for (const spec of specs) {
    const value = record.fields[spec.name];
    form[spec.name] = spec.type === "boolean" ? value === true : textOf(value);
  }
  return form;
}

/** A blank form: empty text, unchecked booleans. */
export function emptyForm(specs: readonly FieldSpec[]): FormValues {
  return Object.fromEntries(specs.map((s) => [s.name, s.type === "boolean" ? false : ""]));
}

const coerce = (spec: FieldSpec, value: string): unknown =>
  NUMBER_TYPES.has(spec.type) ? Number(value) : value;

/** The body of a create: filled fields only (typed), plus every boolean. */
export function buildCreate(
  specs: readonly FieldSpec[],
  form: FormValues,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const spec of specs) {
    const value = form[spec.name];
    if (typeof value === "boolean") body[spec.name] = value;
    else if (value !== undefined && value.trim() !== "") body[spec.name] = coerce(spec, value);
  }
  return body;
}

/** Only the fields whose value differs from the loaded record (empty object: nothing to save). */
export function buildPatch(
  specs: readonly FieldSpec[],
  record: RemoteRecord,
  form: FormValues,
): Record<string, unknown> {
  const original = initialForm(specs, record);
  const patch: Record<string, unknown> = {};
  for (const spec of specs) {
    const next = form[spec.name];
    if (next === undefined || next === original[spec.name]) continue;
    if (typeof next === "boolean") patch[spec.name] = next;
    else if (NUMBER_TYPES.has(spec.type))
      patch[spec.name] = next.trim() === "" ? null : Number(next);
    else patch[spec.name] = next;
  }
  return patch;
}

export interface ParsedFieldErrors {
  fieldErrors: Record<string, string>;
  /** The whole detail when it does not point at any field of the form. */
  general: string | null;
}

/** Reads `cannot edit <model>: field: why; field: why` into per-field messages. */
export function parseFieldErrors(detail: string, known: readonly string[]): ParsedFieldErrors {
  const body = detail.replace(/^cannot edit [^:]+:\s*/, "");
  const fieldErrors: Record<string, string> = {};
  for (const part of body.split(";")) {
    const match = /^\s*([\w.]+):\s*(.+?)\s*$/.exec(part);
    if (match?.[1] && match[2] && known.includes(match[1])) fieldErrors[match[1]] = match[2];
  }
  return {
    fieldErrors,
    general: Object.keys(fieldErrors).length === 0 && detail ? detail : null,
  };
}
