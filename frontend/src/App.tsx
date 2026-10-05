import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { setUnauthorizedHandler } from "@/api/client";
import { SESSION_KEY } from "@/auth/api";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppLayout } from "@/components/AppLayout";
import { ConnectionWizardPage } from "@/features/connections/ConnectionWizardPage";
import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import { NAV_ITEMS } from "@/nav";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

export function App() {
  const queryClient = useQueryClient();

  // An expired session on any call sends the user back to the login page via the guard.
  useEffect(() => {
    setUnauthorizedHandler(() => queryClient.setQueryData(SESSION_KEY, null));
    return () => setUnauthorizedHandler(null);
  }, [queryClient]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/connections/new" element={<ConnectionWizardPage />} />
          <Route path="/connections/:id/edit" element={<ConnectionWizardPage />} />
          {NAV_ITEMS.filter((item) => item.key !== "connections").map((item) => (
            <Route
              key={item.key}
              path={item.path}
              element={<PlaceholderPage section={item.key} />}
            />
          ))}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
