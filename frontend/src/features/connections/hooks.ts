import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ACTIVE_ODOO_KEY,
  activateOdoo,
  createProfile,
  deleteProfile,
  disconnectOdoo,
  getActiveOdoo,
  getProfile,
  listProfiles,
  PROFILES_KEY,
  profileKey,
  testDraft,
  testSaved,
  updateProfile,
} from "@/features/connections/api";
import { DASHBOARD_KEY } from "@/features/dashboard/api";
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

/** How often the active connection is re-read, so a switch made elsewhere shows up. */
export const ACTIVE_ODOO_REFETCH_MS = 30_000;

export const useActiveOdoo = () =>
  useQuery({
    queryKey: ACTIVE_ODOO_KEY,
    queryFn: getActiveOdoo,
    refetchInterval: () => (document.hidden ? false : ACTIVE_ODOO_REFETCH_MS),
  });

/** Everything that shows which Odoo is live: the panel, the profile badges and the dashboard. */
function useInvalidateOdooViews() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ACTIVE_ODOO_KEY }),
      queryClient.invalidateQueries({ queryKey: PROFILES_KEY }),
      queryClient.invalidateQueries({ queryKey: DASHBOARD_KEY }),
    ]);
}

export function useActivateOdoo() {
  const invalidate = useInvalidateOdooViews();
  return useMutation({
    mutationFn: (profileId: number) => activateOdoo(profileId),
    onSuccess: invalidate,
  });
}

export function useDisconnectOdoo() {
  const invalidate = useInvalidateOdooViews();
  return useMutation({ mutationFn: () => disconnectOdoo(), onSuccess: invalidate });
}
