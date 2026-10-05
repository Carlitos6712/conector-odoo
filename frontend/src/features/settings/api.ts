import { api } from "@/api/client";
import type { AdminUser, Role } from "@/auth/api";

export const USERS_KEY = ["users"] as const;

export interface UserCreateInput {
  username: string;
  password: string;
  role: Role;
}

/** PATCH takes a role, a password or both (the API rejects an empty patch). */
export interface UserPatch {
  role?: Role;
  password?: string;
}

export const listUsers = async (): Promise<AdminUser[]> =>
  (await api.get<{ items: AdminUser[] }>("/users")).items;

export const createUser = (input: UserCreateInput) => api.post<AdminUser>("/users", input);

export const updateUser = (id: number, patch: UserPatch) =>
  api.patch<AdminUser>(`/users/${id}`, patch);

export const deleteUser = (id: number) => api.delete<void>(`/users/${id}`);
