import { api } from "@/api/client";
import type { RecordPage, RecordTarget, RemoteRecord } from "@/features/records/types";

export const RECORDS_KEY = ["records"] as const;

export interface ListParams extends RecordTarget {
  search: string;
  limit: number;
  offset: number;
}

const recordsPath = ({ profileId, resource }: RecordTarget) =>
  `/profiles/${profileId}/records/${encodeURIComponent(resource)}`;

export const recordsKey = (params: ListParams) => [...RECORDS_KEY, params] as const;

export function listRecords(params: ListParams, signal?: AbortSignal) {
  const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) });
  if (params.search) query.set("search", params.search);
  return api.get<RecordPage>(`${recordsPath(params)}?${query.toString()}`, { signal });
}

/** Changes ONE record; `fields` holds only what the user modified. */
export const updateRecord = (
  target: RecordTarget,
  id: string | number,
  fields: Record<string, unknown>,
) =>
  api.patch<RemoteRecord>(`${recordsPath(target)}/${encodeURIComponent(String(id))}`, { fields });

/** Deletes ONE record. There is deliberately no collection-level variant. */
export const deleteRecord = (target: RecordTarget, id: string | number) =>
  api.delete<void>(`${recordsPath(target)}/${encodeURIComponent(String(id))}`);
