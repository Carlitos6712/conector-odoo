import { nextFires, validateCron } from "@/features/jobs/cron";
import type {
  ConflictRule,
  Direction,
  Job,
  JobInput,
  RecordFilterDoc,
  TriggerDoc,
} from "@/features/jobs/types";
import { formatLiteral, parseLiteral } from "@/features/mappings/model";
import type { MappingDoc, StoredMapping } from "@/features/mappings/types";

export const JOB_STEPS = ["basics", "endpoints", "options", "trigger", "review"] as const;
export type JobStep = (typeof JOB_STEPS)[number];

export const MAX_NAME_LENGTH = 120;
export const MAX_BATCH_SIZE = 1000;

export interface FilterRow {
  field: string;
  /** Typed like the mapping editor's literals (`true`, `42`, `"007"`, plain text). */
  value: string;
}

/** Everything the wizard edits, as text so inputs stay controlled. */
export interface JobFormState {
  name: string;
  direction: Direction;
  sourceProfileId: string;
  sourceResource: string;
  targetProfileId: string;
  targetResource: string;
  mappingName: string;
  /** Empty = follow the latest version. */
  mappingVersion: string;
  reverseName: string;
  reverseVersion: string;
  upsertKind: "xref" | "field";
  upsertField: string;
  filters: FilterRow[];
  /** `since` and `raw` have no editor yet: they are carried through unchanged. */
  preservedSince: string | null;
  preservedRaw: Record<string, unknown> | null;
  batchSize: string;
  conflictRule: ConflictRule;
  sourceUpdatedField: string;
  targetUpdatedField: string;
  triggerKind: TriggerDoc["kind"];
  cron: string;
  eventTypes: string[];
  enabled: boolean;
}

export type JobFieldName =
  | "name"
  | "sourceProfile"
  | "sourceResource"
  | "targetProfile"
  | "targetResource"
  | "mapping"
  | "reverseMapping"
  | "batchSize"
  | "upsertField"
  | "filters"
  | "sourceUpdatedField"
  | "targetUpdatedField"
  | "cron"
  | "eventTypes";

export type JobFieldErrors = Partial<Record<JobFieldName, string>>;

export const emptyJobState = (): JobFormState => ({
  name: "",
  direction: "a_to_b",
  sourceProfileId: "",
  sourceResource: "",
  targetProfileId: "",
  targetResource: "",
  mappingName: "",
  mappingVersion: "",
  reverseName: "",
  reverseVersion: "",
  upsertKind: "xref",
  upsertField: "",
  filters: [],
  preservedSince: null,
  preservedRaw: null,
  batchSize: "100",
  conflictRule: "source_wins",
  sourceUpdatedField: "",
  targetUpdatedField: "",
  triggerKind: "manual",
  cron: "0 2 * * *",
  eventTypes: [],
  enabled: true,
});

const FIELD_PREFIX = "field:";

export function stateFromJob(job: Job | JobInput): JobFormState {
  const key = job.upsert_key;
  return {
    name: job.name,
    direction: job.direction,
    sourceProfileId: String(job.source.profile_id),
    sourceResource: job.source.resource,
    targetProfileId: String(job.target.profile_id),
    targetResource: job.target.resource,
    mappingName: job.mapping.name,
    mappingVersion: job.mapping.version === null ? "" : String(job.mapping.version),
    reverseName: job.reverse_mapping?.name ?? "",
    reverseVersion:
      job.reverse_mapping?.version === null || job.reverse_mapping === null
        ? ""
        : String(job.reverse_mapping.version),
    upsertKind: key.startsWith(FIELD_PREFIX) ? "field" : "xref",
    upsertField: key.startsWith(FIELD_PREFIX) ? key.slice(FIELD_PREFIX.length) : "",
    filters: Object.entries(job.record_filter.equals).map(([field, value]) => ({
      field,
      value: formatLiteral(value),
    })),
    preservedSince: job.record_filter.since,
    preservedRaw: job.record_filter.raw,
    batchSize: String(job.batch_size),
    conflictRule: job.conflict_rule,
    sourceUpdatedField: job.source_updated_field ?? "",
    targetUpdatedField: job.target_updated_field ?? "",
    triggerKind: job.trigger.kind,
    cron: job.trigger.kind === "schedule" ? job.trigger.cron : emptyJobState().cron,
    eventTypes: job.trigger.kind === "webhook" ? [...job.trigger.event_types] : [],
    enabled: job.enabled,
  };
}

/** The editable part of a stored job, as `PUT /jobs/{id}` expects it. */
export function jobToInput(job: Job): JobInput {
  const input: Partial<Job> = { ...job };
  delete input.id;
  delete input.next_fire;
  return input as JobInput;
}

const normalizeCron = (cron: string) => cron.trim().split(/\s+/).join(" ");
const versionOf = (text: string): number | null => (text.trim() === "" ? null : Number(text));

function triggerOf(state: JobFormState): TriggerDoc {
  if (state.triggerKind === "schedule")
    return { kind: "schedule", cron: normalizeCron(state.cron) };
  if (state.triggerKind === "webhook") return { kind: "webhook", event_types: state.eventTypes };
  return { kind: "manual" };
}

/**
 * `newest_wins` is only meaningful with both updated-at fields; a one way job has no use for a
 * conflict rule, so one left over from a bidirectional draft must not make the backend refuse it.
 */
function effectiveConflictRule(state: JobFormState): ConflictRule {
  const hasFields =
    state.sourceUpdatedField.trim() !== "" && state.targetUpdatedField.trim() !== "";
  if (state.conflictRule === "newest_wins" && !hasFields && state.direction !== "bidirectional") {
    return "source_wins";
  }
  return state.conflictRule;
}

export function toJobInput(state: JobFormState): JobInput {
  const equals: Record<string, unknown> = {};
  for (const row of state.filters) {
    if (row.field.trim() !== "") equals[row.field.trim()] = parseLiteral(row.value);
  }
  const recordFilter: RecordFilterDoc = {
    equals,
    since: state.preservedSince,
    raw: state.preservedRaw,
  };
  const conflictRule = effectiveConflictRule(state);
  const newest = conflictRule === "newest_wins";
  return {
    name: state.name.trim(),
    source: { profile_id: Number(state.sourceProfileId), resource: state.sourceResource.trim() },
    target: { profile_id: Number(state.targetProfileId), resource: state.targetResource.trim() },
    mapping: { name: state.mappingName, version: versionOf(state.mappingVersion) },
    reverse_mapping:
      state.direction === "a_to_b" || state.reverseName === ""
        ? null
        : { name: state.reverseName, version: versionOf(state.reverseVersion) },
    direction: state.direction,
    trigger: triggerOf(state),
    record_filter: recordFilter,
    batch_size: Number(state.batchSize),
    upsert_key:
      state.upsertKind === "field" ? `${FIELD_PREFIX}${state.upsertField.trim()}` : "xref",
    conflict_rule: conflictRule,
    source_updated_field: newest ? state.sourceUpdatedField.trim() : null,
    target_updated_field: newest ? state.targetUpdatedField.trim() : null,
    enabled: state.enabled,
  };
}

// -- validation --------------------------------------------------------------------------------

const REQUIRED = "jobs.errors.required";
const blank = (text: string) => text.trim() === "";

function validateBasics(state: JobFormState): JobFieldErrors {
  if (blank(state.name)) return { name: "jobs.errors.nameRequired" };
  if (state.name.trim().length > MAX_NAME_LENGTH) return { name: "jobs.errors.nameTooLong" };
  return {};
}

function validateEndpoints(state: JobFormState): JobFieldErrors {
  const errors: JobFieldErrors = {};
  if (blank(state.sourceProfileId)) errors.sourceProfile = REQUIRED;
  if (blank(state.sourceResource)) errors.sourceResource = REQUIRED;
  if (blank(state.targetProfileId)) errors.targetProfile = REQUIRED;
  if (blank(state.targetResource)) errors.targetResource = REQUIRED;
  if (blank(state.mappingName)) errors.mapping = REQUIRED;
  if (state.direction !== "a_to_b" && blank(state.reverseName)) errors.reverseMapping = REQUIRED;
  return errors;
}

function validateOptions(state: JobFormState): JobFieldErrors {
  const errors: JobFieldErrors = {};
  const size = Number(state.batchSize);
  if (blank(state.batchSize) || !Number.isInteger(size) || size < 1 || size > MAX_BATCH_SIZE) {
    errors.batchSize = "jobs.errors.batchSize";
  }
  if (state.upsertKind === "field" && blank(state.upsertField)) errors.upsertField = REQUIRED;

  const seen = new Set<string>();
  for (const row of state.filters) {
    if (blank(row.field)) {
      if (!blank(row.value)) errors.filters = "jobs.errors.filterField";
    } else if (seen.has(row.field.trim())) {
      errors.filters = "jobs.errors.filterDuplicate";
    } else {
      seen.add(row.field.trim());
    }
  }
  if (effectiveConflictRule(state) === "newest_wins") {
    if (blank(state.sourceUpdatedField)) errors.sourceUpdatedField = REQUIRED;
    if (blank(state.targetUpdatedField)) errors.targetUpdatedField = REQUIRED;
  }
  return errors;
}

function validateTrigger(state: JobFormState): JobFieldErrors {
  if (state.triggerKind === "schedule") {
    const issue = validateCron(state.cron);
    if (issue) return { cron: `jobs.cron.errors.${issue.code}` };
    if (nextFires(state.cron, new Date(), 1).length === 0) return { cron: "jobs.cron.neverFires" };
  }
  if (state.triggerKind === "webhook" && state.eventTypes.length === 0) {
    return { eventTypes: "jobs.errors.eventTypes" };
  }
  return {};
}

export function validateStep(step: JobStep, state: JobFormState): JobFieldErrors {
  switch (step) {
    case "basics":
      return validateBasics(state);
    case "endpoints":
      return validateEndpoints(state);
    case "options":
      return validateOptions(state);
    case "trigger":
      return validateTrigger(state);
    default:
      return {};
  }
}

export const validateAll = (state: JobFormState): JobFieldErrors => ({
  ...validateBasics(state),
  ...validateEndpoints(state),
  ...validateOptions(state),
  ...validateTrigger(state),
});

const FIELD_STEP: Record<JobFieldName, JobStep> = {
  name: "basics",
  sourceProfile: "endpoints",
  sourceResource: "endpoints",
  targetProfile: "endpoints",
  targetResource: "endpoints",
  mapping: "endpoints",
  reverseMapping: "endpoints",
  batchSize: "options",
  upsertField: "options",
  filters: "options",
  sourceUpdatedField: "options",
  targetUpdatedField: "options",
  cron: "trigger",
  eventTypes: "trigger",
};

export const stepOfField = (field: JobFieldName): JobStep => FIELD_STEP[field];

// -- mapping compatibility ---------------------------------------------------------------------

/** Does the mapping read `source` and write `target` (the backend's `check_job_mappings`)? */
export const mappingMatches = (definition: MappingDoc, source: string, target: string): boolean =>
  definition.source_resource === source && definition.target_resource === target;

export const compatibleMappings = (
  mappings: readonly StoredMapping[],
  source: string,
  target: string,
): StoredMapping[] =>
  source === "" || target === ""
    ? []
    : mappings.filter((mapping) => mappingMatches(mapping.definition, source, target));

/**
 * The selected mappings against the saved ones, before the server has to say it: the same rule
 * as `check_job_mappings` (forward reads the source and writes the target, reverse the opposite).
 */
export function checkMappings(
  state: JobFormState,
  mappings: readonly StoredMapping[],
): JobFieldErrors {
  const errors: JobFieldErrors = {};
  const inspect = (name: string, source: string, target: string): string | undefined => {
    if (name === "") return undefined;
    const found = mappings.find((mapping) => mapping.name === name);
    if (found === undefined) return "jobs.errors.referenceMissing";
    return mappingMatches(found.definition, source, target)
      ? undefined
      : "jobs.errors.mappingMismatch";
  };
  const forward = inspect(
    state.mappingName,
    state.sourceResource.trim(),
    state.targetResource.trim(),
  );
  if (forward) errors.mapping = forward;
  if (state.direction !== "a_to_b") {
    const back = inspect(
      state.reverseName,
      state.targetResource.trim(),
      state.sourceResource.trim(),
    );
    if (back) errors.reverseMapping = back;
  }
  return errors;
}
