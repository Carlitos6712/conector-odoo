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
        <aside className="flex flex-col gap-4 border-b border-sidebar-border bg-sidebar p-4 text-sidebar-foreground md:w-60 md:border-r md:border-b-0">
          <p className="rounded-lg bg-gradient-to-br from-brand-from to-brand-to px-3 py-2.5 text-lg font-semibold tracking-tight text-white shadow-soft">
            {t("app.name")}
          </p>
          <nav aria-label={t("nav.label")}>
            <ul className="flex flex-wrap gap-1 md:flex-col">
              {items.map(({ key, path, icon: Icon }) => (
                <li key={key}>
                  <NavLink
                    to={path}
                    end={path === "/"}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2 rounded-md border-l-2 border-transparent px-3 py-2 text-sm text-sidebar-muted transition-colors hover:bg-sidebar-hover hover:text-sidebar-foreground focus-visible:outline-2 focus-visible:outline-white/70",
                        isActive &&
                          "border-white bg-sidebar-active font-medium text-sidebar-foreground",
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
                <span className="text-sidebar-muted">{t(`session.roles.${user.role}`)}</span>
              </p>
              <Button
                variant="outline"
                size="sm"
                className="border-sidebar-border bg-transparent text-sidebar-foreground hover:border-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground"
                onClick={() => signOut.mutate()}
              >
                <LogOut aria-hidden className="size-4" />
                {t("session.logout")}
              </Button>
            </div>
          )}
        </aside>
        <div className="flex flex-1 flex-col">
          {user && !isAdmin && (
            <p
              role="status"
              className="border-b border-info-soft-foreground/20 bg-info-soft px-6 py-2 text-sm text-info-soft-foreground"
            >
              {t("session.readOnly")}
            </p>
          )}
          <main
            id="main"
            className="flex-1 bg-gradient-to-b from-brand-soft/60 to-transparent to-[240px] p-6"
          >
            <Outlet />
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
