import type { FieldSpec } from "@/features/resources/types";

export type { FieldSpec };

export interface RemoteRecord {
  id: string | number;
  fields: Record<string, unknown>;
}

export interface RecordSchema {
  name: string;
  label: string;
  id_field: string;
  fields: FieldSpec[];
}

export interface RecordPage {
  items: RemoteRecord[];
  schema: RecordSchema;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface RecordTarget {
  profileId: number;
  resource: string;
}

/** What happened to the counterpart of a written record for one bidirectional job. */
export interface PropagationOutcome {
  job_id: number | null;
  job_name: string;
  side: string;
  action: "created" | "updated" | "deleted" | "skipped" | "failed";
  counterpart_id: string | null;
  warning: string | null;
}

/** Write-through report returned by create, edit and delete. */
export interface PropagationReport {
  propagation: PropagationOutcome[];
  warnings: string[];
}

export interface RecordWriteResult extends RemoteRecord, PropagationReport {}

export type WriteKind = "create" | "update" | "delete";
