/** Wire shapes of `/admin/api/jobs` (see `admin_api/schemas/jobs.py`). */
export type Direction = "a_to_b" | "b_to_a" | "bidirectional";
export type ConflictRule = "source_wins" | "target_wins" | "newest_wins" | "flag_conflict";

export const DIRECTIONS: readonly Direction[] = ["a_to_b", "b_to_a", "bidirectional"];
export const CONFLICT_RULES: readonly ConflictRule[] = [
  "source_wins",
  "target_wins",
  "newest_wins",
  "flag_conflict",
];

/** Event types the webhook intake can publish (`domain/events.py`). */
export const KNOWN_EVENT_TYPES = ["partner.created", "partner.updated", "sale_order.confirmed"];

export interface EndpointRef {
  profile_id: number;
  resource: string;
}

/** `version: null` follows the latest version of the mapping. */
export interface MappingRef {
  name: string;
  version: number | null;
}

export type TriggerDoc =
  | { kind: "manual" }
  | { kind: "schedule"; cron: string }
  | { kind: "webhook"; event_types: string[] };

export interface RecordFilterDoc {
  equals: Record<string, unknown>;
  since: string | null;
  raw: Record<string, unknown> | null;
}

/** What `POST /jobs` and `PUT /jobs/{id}` accept. */
export interface JobInput {
  name: string;
  source: EndpointRef;
  target: EndpointRef;
  mapping: MappingRef;
  reverse_mapping: MappingRef | null;
  direction: Direction;
  trigger: TriggerDoc;
  record_filter: RecordFilterDoc;
  /** Selection for the reverse pass of a bidirectional run; its field names belong to side B. */
  reverse_record_filter: RecordFilterDoc;
  batch_size: number;
  /** `xref` or `field:<target field>`. */
  upsert_key: string;
  conflict_rule: ConflictRule;
  source_updated_field: string | null;
  target_updated_field: string | null;
  enabled: boolean;
}

export interface Job extends JobInput {
  id: number;
  /** Next scheduled UTC fire as the in-process scheduler sees it; null when not scheduled. */
  next_fire: string | null;
}

export interface TriggerRunRequest {
  jobId: number;
  dryRun: boolean;
}
