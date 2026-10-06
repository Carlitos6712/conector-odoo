import { api, ApiError, csrfStore } from "@/api/client";

export type Role = "admin" | "operator";

export interface AdminUser {
  id: number;
  username: string;
  role: Role;
  created_at: string;
}

export interface Session {
  user: AdminUser;
  csrf_token: string;
  expires_at: string;
}

export const SESSION_KEY = ["auth", "me"] as const;

function remember(session: Session): Session {
  csrfStore.set(session.csrf_token);
  return session;
}

/** Current session, or `null` when nobody is signed in (401 is an answer, not a failure). */
export async function fetchSession(): Promise<Session | null> {
  try {
    return remember(await api.get<Session>("/auth/me"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function login(username: string, password: string): Promise<Session> {
  const session = await api.post<Session>(
    "/auth/login",
    { username, password },
    { handleUnauthorized: false },
  );
  return remember(session);
}

/** Own password change (any role). The answer is the rotated session: adopt its CSRF token. */
export async function changePassword(current: string, next: string): Promise<Session> {
  const session = await api.post<Session>("/auth/password", {
    current_password: current,
    new_password: next,
  });
  return remember(session);
}

export async function logout(): Promise<void> {
  try {
    await api.post<void>("/auth/logout", undefined, { handleUnauthorized: false });
  } finally {
    csrfStore.clear();
  }
}
