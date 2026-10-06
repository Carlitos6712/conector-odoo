import { api } from "@/api/client";
import type { ConnectionTestResult, Profile, ProfileInput } from "@/features/connections/types";

export const PROFILES_KEY = ["profiles"] as const;
export const profileKey = (id: number) => [...PROFILES_KEY, id] as const;

export const listProfiles = async (): Promise<Profile[]> =>
  (await api.get<{ items: Profile[] }>("/profiles")).items;

export const getProfile = (id: number) => api.get<Profile>(`/profiles/${id}`);

export const createProfile = (input: ProfileInput) => api.post<Profile>("/profiles", input);

export const updateProfile = (id: number, input: ProfileInput) =>
  api.put<Profile>(`/profiles/${id}`, input);

export const deleteProfile = (id: number) => api.delete<void>(`/profiles/${id}`);

/** Probes an unsaved profile: nothing is stored server-side. */
export const testDraft = (input: ProfileInput) =>
  api.post<ConnectionTestResult>("/profiles/test", input);

export const testSaved = (id: number) => api.post<ConnectionTestResult>(`/profiles/${id}/test`);
