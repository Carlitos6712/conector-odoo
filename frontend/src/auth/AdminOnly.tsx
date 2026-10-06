import type { ReactNode } from "react";
import { useSession } from "@/auth/useSession";

/** Renders mutating controls for admins only (operators are read-only). */
export function AdminOnly({
  children,
  fallback = null,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { canMutate } = useSession();
  return <>{canMutate ? children : fallback}</>;
}
