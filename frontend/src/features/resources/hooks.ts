import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteResource,
  discoverModels,
  getResource,
  importOpenApi,
  listResources,
  previewResource,
  profileResourcesKey,
  resourceKey,
  RESOURCES_KEY,
  saveResource,
} from "@/features/resources/api";
import type { ImportRequest, ResourceInput } from "@/features/resources/types";

export const useResources = (profileId: number | null) =>
  useQuery({
    queryKey: profileResourcesKey(profileId ?? -1),
    queryFn: () => listResources(profileId ?? -1),
    enabled: profileId !== null,
  });

/** One listing per profile, for the "all connections" view. */
export const useAllResources = (profileIds: readonly number[]) =>
  useQueries({
    queries: profileIds.map((id) => ({
      queryKey: profileResourcesKey(id),
      queryFn: () => listResources(id),
    })),
  });

export const useResource = (profileId: number | null, name: string | null) =>
  useQuery({
    queryKey: resourceKey(profileId ?? -1, name ?? ""),
    queryFn: () => getResource(profileId ?? -1, name ?? ""),
    enabled: profileId !== null && name !== null,
  });

export function useSaveResource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ profileId, input }: { profileId: number; input: ResourceInput }) =>
      saveResource(profileId, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RESOURCES_KEY }),
  });
}

export function useDeleteResource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ profileId, name }: { profileId: number; name: string }) =>
      deleteResource(profileId, name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RESOURCES_KEY }),
  });
}

/**
 * A preview is a POST (it contacts the remote system) but reads like a query: it runs when the
 * panel opens and can be re-run. Results are never cached beyond the panel.
 */
export const usePreview = (profileId: number, name: string, limit = 5, enabled = true) =>
  useQuery({
    queryKey: [...resourceKey(profileId, name), "preview", limit],
    queryFn: () => previewResource(profileId, name, limit),
    enabled,
    gcTime: 0,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });

/** Saves nothing: the report only lists candidates and warnings. */
export const useImportOpenApi = () =>
  useMutation({
    gcTime: 0,
    mutationFn: ({ profileId, request }: { profileId: number; request: ImportRequest }) =>
      importOpenApi(profileId, request),
  });

export const useDiscoverModels = (profileId: number | null, enabled = true) =>
  useQuery({
    queryKey: [...RESOURCES_KEY, "discover", profileId ?? -1],
    queryFn: () => discoverModels(profileId ?? -1),
    enabled: enabled && profileId !== null,
    retry: false,
    refetchOnWindowFocus: false,
  });
