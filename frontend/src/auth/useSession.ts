import { useQuery } from "@tanstack/react-query";
import { fetchSession, SESSION_KEY, type AdminUser } from "@/auth/api";

/** Session state plus the role helpers every screen uses to hide mutating actions. */
export function useSession() {
  const query = useQuery({
    queryKey: SESSION_KEY,
    queryFn: fetchSession,
    staleTime: Infinity,
    retry: false,
  });
  const user: AdminUser | null = query.data?.user ?? null;
  return {
    query,
    user,
    isAdmin: user?.role === "admin",
    /** Operators are read-only: mutating actions must be hidden or disabled when false. */
    canMutate: user?.role === "admin",
  };
}
