import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createProfile,
  deleteProfile,
  getProfile,
  listProfiles,
  PROFILES_KEY,
  profileKey,
  testDraft,
  testSaved,
  updateProfile,
} from "@/features/connections/api";
import type { ProfileInput } from "@/features/connections/types";

export const useProfiles = () => useQuery({ queryKey: PROFILES_KEY, queryFn: listProfiles });

export const useProfile = (id: number | null) =>
  useQuery({
    queryKey: profileKey(id ?? -1),
    queryFn: () => getProfile(id ?? -1),
    enabled: id !== null,
  });

/**
 * Mutations carrying credentials use `gcTime: 0` so their variables leave the mutation cache as
 * soon as the form unmounts.
 */
const SECRET_SAFE = { gcTime: 0 } as const;

export function useCreateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    ...SECRET_SAFE,
    mutationFn: (input: ProfileInput) => createProfile(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROFILES_KEY }),
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    ...SECRET_SAFE,
    mutationFn: ({ id, input }: { id: number; input: ProfileInput }) => updateProfile(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROFILES_KEY }),
  });
}

export function useDeleteProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => deleteProfile(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PROFILES_KEY }),
  });
}

export const useTestDraft = () =>
  useMutation({ ...SECRET_SAFE, mutationFn: (input: ProfileInput) => testDraft(input) });

export const useTestSaved = () =>
  useMutation({ ...SECRET_SAFE, mutationFn: (id: number) => testSaved(id) });
