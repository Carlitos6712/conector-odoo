import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteMapping,
  dryRun,
  getMapping,
  listMappings,
  listVersions,
  MAPPINGS_KEY,
  mappingKey,
  saveMapping,
  suggest,
  versionsKey,
} from "@/features/mappings/api";

export const useMappings = () => useQuery({ queryKey: MAPPINGS_KEY, queryFn: listMappings });

export const useMapping = (name: string | null, version?: number) =>
  useQuery({
    queryKey: mappingKey(name ?? "", version),
    queryFn: () => getMapping(name ?? "", version),
    enabled: name !== null,
  });

export const useMappingVersions = (name: string) =>
  useQuery({ queryKey: versionsKey(name), queryFn: () => listVersions(name) });

export function useSaveMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: saveMapping,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MAPPINGS_KEY }),
  });
}

export function useDeleteMapping() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteMapping,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: MAPPINGS_KEY }),
  });
}

/** Dry-run results are samples of live data: never kept beyond the panel. */
export const useDryRun = () => useMutation({ gcTime: 0, mutationFn: dryRun });

/** Suggestions only pre-fill the editor; nothing is stored. */
export const useSuggest = () => useMutation({ gcTime: 0, mutationFn: suggest });
