import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { logout, SESSION_KEY } from "@/auth/api";
import { useSession } from "@/auth/useSession";
import { Button } from "@/components/ui/button";
import { ToastProvider } from "@/components/ui/toast";
import { NAV_ITEMS } from "@/nav";
import { cn } from "@/lib/utils";

export function AppLayout() {
  const { t } = useTranslation();
  const { user, isAdmin } = useSession();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(SESSION_KEY, null);
      void navigate("/login", { replace: true });
    },
  });

  const items = NAV_ITEMS.filter((item) => isAdmin || !item.adminOnly);

  return (
    <ToastProvider>
      <div className="flex min-h-screen flex-col md:flex-row">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded-md focus:bg-background focus:p-2"
        >
          {t("app.skipToContent")}
        </a>
        <aside className="flex flex-col gap-4 border-b bg-card p-4 md:w-60 md:border-r md:border-b-0">
          <p className="text-lg font-semibold">{t("app.name")}</p>
          <nav aria-label={t("nav.label")}>
            <ul className="flex flex-wrap gap-1 md:flex-col">
              {items.map(({ key, path, icon: Icon }) => (
                <li key={key}>
                  <NavLink
                    to={path}
                    end={path === "/"}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                        isActive && "bg-accent font-medium",
                      )
                    }
                  >
                    <Icon aria-hidden className="size-4" />
                    {t(`nav.${key}`)}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          {user && (
            <div className="mt-auto flex flex-col gap-2 text-sm">
              <p>
                <span className="font-medium">{user.username}</span>
                <br />
                <span className="text-muted-foreground">{t(`session.roles.${user.role}`)}</span>
              </p>
              <Button variant="outline" size="sm" onClick={() => signOut.mutate()}>
                <LogOut aria-hidden className="size-4" />
                {t("session.logout")}
              </Button>
            </div>
          )}
        </aside>
        <div className="flex flex-1 flex-col">
          {user && !isAdmin && (
            <p role="status" className="border-b bg-muted px-6 py-2 text-sm text-muted-foreground">
              {t("session.readOnly")}
            </p>
          )}
          <main id="main" className="flex-1 p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
