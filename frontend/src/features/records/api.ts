import { api } from "@/api/client";
import type {
  PropagationReport,
  RecordPage,
  RecordTarget,
  RecordWriteResult,
} from "@/features/records/types";

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

/** Creates ONE record; the id is assigned by the system, never supplied. */
export const createRecord = (target: RecordTarget, fields: Record<string, unknown>) =>
  api.post<RecordWriteResult>(recordsPath(target), { fields });

/** Changes ONE record; `fields` holds only what the user modified. */
export const updateRecord = (
  target: RecordTarget,
  id: string | number,
  fields: Record<string, unknown>,
) =>
  api.patch<RecordWriteResult>(`${recordsPath(target)}/${encodeURIComponent(String(id))}`, {
    fields,
  });

/** Deletes ONE record. There is deliberately no collection-level variant. */
export async function deleteRecord(
  target: RecordTarget,
  id: string | number,
): Promise<PropagationReport> {
  const body = await api.delete<PropagationReport | undefined>(
    `${recordsPath(target)}/${encodeURIComponent(String(id))}`,
  );
  // An older backend answered 204 with no body: nothing was propagated.
  return body ?? { propagation: [], warnings: [] };
}
