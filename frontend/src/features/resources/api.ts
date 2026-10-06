import { api } from "@/api/client";
import type {
  DiscoveredModel,
  ImportReport,
  ImportRequest,
  PreviewResult,
  ResourceInput,
  ResourceListing,
  StoredResource,
} from "@/features/resources/types";

export const RESOURCES_KEY = ["resources"] as const;
export const profileResourcesKey = (profileId: number) => [...RESOURCES_KEY, profileId] as const;
export const resourceKey = (profileId: number, name: string) =>
  [...profileResourcesKey(profileId), name] as const;

const base = (profileId: number) => `/profiles/${profileId}`;
const resourcePath = (profileId: number, name: string) =>
  `${base(profileId)}/resources/${encodeURIComponent(name)}`;

export const listResources = (profileId: number) =>
  api.get<ResourceListing>(`${base(profileId)}/resources`);

export const getResource = (profileId: number, name: string) =>
  api.get<StoredResource>(resourcePath(profileId, name));

export const saveResource = (profileId: number, input: ResourceInput) =>
  api.put<StoredResource>(resourcePath(profileId, input.name), input);

export const deleteResource = (profileId: number, name: string) =>
  api.delete<void>(resourcePath(profileId, name));

/** Contacts the remote system with the stored credentials, hence a POST (admin only). */
export const previewResource = (profileId: number, name: string, limit: number) =>
  api.post<PreviewResult>(`${resourcePath(profileId, name)}/preview?limit=${limit}`);

export const importOpenApi = (profileId: number, request: ImportRequest) =>
  api.post<ImportReport>(`${base(profileId)}/resources/import`, request);

export const discoverModels = async (profileId: number): Promise<DiscoveredModel[]> =>
  (await api.post<{ items: DiscoveredModel[] }>(`${base(profileId)}/discover`)).items;
