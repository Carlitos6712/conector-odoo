import { api } from "@/api/client";
import { previewResource } from "@/features/resources/api";
import type {
  DryRunReport,
  DryRunResult,
  MappingDoc,
  SaveResult,
  StoredMapping,
  Suggestion,
} from "@/features/mappings/types";

export const MAPPINGS_KEY = ["mappings"] as const;
export const mappingKey = (name: string, version?: number) =>
  [...MAPPINGS_KEY, name, version ?? "latest"] as const;
export const versionsKey = (name: string) => [...MAPPINGS_KEY, name, "versions"] as const;

const path = (name: string) => `/mappings/${encodeURIComponent(name)}`;

export const listMappings = async (): Promise<StoredMapping[]> =>
  (await api.get<{ items: StoredMapping[] }>("/mappings")).items;

export const getMapping = (name: string, version?: number) =>
  api.get<StoredMapping>(version === undefined ? path(name) : `${path(name)}?version=${version}`);

export const listVersions = async (name: string): Promise<StoredMapping[]> =>
  (await api.get<{ items: StoredMapping[] }>(`${path(name)}/versions`)).items;

export interface SaveRequest {
  name: string;
  definition: MappingDoc;
  /** Optional: when given the server also checks the definition against the live schemas. */
  sourceProfileId?: number;
  targetProfileId?: number;
}

export const saveMapping = ({ name, definition, sourceProfileId, targetProfileId }: SaveRequest) =>
  api.put<SaveResult>(path(name), {
    definition,
    ...(sourceProfileId === undefined ? {} : { source_profile_id: sourceProfileId }),
    ...(targetProfileId === undefined ? {} : { target_profile_id: targetProfileId }),
  });

export const deleteMapping = (name: string) => api.delete<void>(path(name));

export interface DryRunRequest {
  definition: MappingDoc;
  sourceProfileId: number;
  targetProfileId: number;
  limit: number;
}

/**
 * Contacts the remote systems (hence a POST, admin only). The report carries only the mapped
 * output, so the input side comes from a preview of the same source; if that fails the report
 * is still returned without inputs.
 */
export async function dryRun(request: DryRunRequest): Promise<DryRunResult> {
  const { definition, sourceProfileId, targetProfileId, limit } = request;
  const [report, preview] = await Promise.allSettled([
    api.post<DryRunReport>("/mappings/dry-run", {
      definition,
      source_profile_id: sourceProfileId,
      target_profile_id: targetProfileId,
      limit,
    }),
    previewResource(sourceProfileId, definition.source_resource, limit),
  ]);
  if (report.status === "rejected") throw report.reason;
  const inputs: DryRunResult["inputs"] = {};
  if (preview.status === "fulfilled") {
    for (const record of preview.value.records) {
      if (record.id !== null) inputs[record.id] = record.fields;
    }
  }
  return { report: report.value, inputs };
}

export interface SuggestRequest {
  sourceProfileId: number;
  sourceResource: string;
  targetProfileId: number;
  targetResource: string;
}

export const suggest = (request: SuggestRequest) =>
  api.post<Suggestion>("/mappings/suggest", {
    source_profile_id: request.sourceProfileId,
    source_resource: request.sourceResource,
    target_profile_id: request.targetProfileId,
    target_resource: request.targetResource,
  });
