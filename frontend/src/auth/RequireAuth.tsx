import { Navigate, Outlet, useLocation } from "react-router-dom";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { useSession } from "@/auth/useSession";

/** Route guard: anonymous visitors go to /login and come back to where they were headed. */
export function RequireAuth() {
  const { query, user } = useSession();
  const location = useLocation();

  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}
