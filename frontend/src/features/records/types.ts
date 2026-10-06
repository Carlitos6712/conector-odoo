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
