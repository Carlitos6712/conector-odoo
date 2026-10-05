import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { changePassword, SESSION_KEY } from "@/auth/api";
import {
  createUser,
  deleteUser,
  listUsers,
  updateUser,
  USERS_KEY,
  type UserPatch,
} from "@/features/settings/api";

export const useUsers = (enabled = true) =>
  useQuery({ queryKey: USERS_KEY, queryFn: listUsers, enabled });

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: UserPatch }) => updateUser(id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteUser,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

/** The server rotates the session on success: the new cookie is set by the browser and the new
 * CSRF token is adopted here, so the caller stays signed in. */
export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ current, next }: { current: string; next: string }) =>
      changePassword(current, next),
    onSuccess: (session) => queryClient.setQueryData(SESSION_KEY, session),
  });
}
