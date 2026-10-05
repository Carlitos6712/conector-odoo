import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Route, Routes } from "react-router-dom";
import { setUnauthorizedHandler } from "@/api/client";
import { SESSION_KEY } from "@/auth/api";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppLayout } from "@/components/AppLayout";
import { ConnectionWizardPage } from "@/features/connections/ConnectionWizardPage";
import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import { JobsPage } from "@/features/jobs/JobsPage";
import { MappingEditorPage } from "@/features/mappings/MappingEditorPage";
import { MappingVersionsPage } from "@/features/mappings/MappingVersionsPage";
import { MappingsPage } from "@/features/mappings/MappingsPage";
import { ImportPage } from "@/features/resources/ImportPage";
import { ResourceEditorPage } from "@/features/resources/ResourceEditorPage";
import { ResourcesPage } from "@/features/resources/ResourcesPage";
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
          <Route path="/resources" element={<ResourcesPage />} />
          <Route path="/resources/import" element={<ImportPage />} />
          <Route path="/resources/new" element={<ResourceEditorPage />} />
          <Route path="/resources/:profileId/:name/edit" element={<ResourceEditorPage />} />
          <Route path="/mappings" element={<MappingsPage />} />
          <Route path="/mappings/new" element={<MappingEditorPage />} />
          <Route path="/mappings/:name/edit" element={<MappingEditorPage />} />
          <Route path="/mappings/:name/versions" element={<MappingVersionsPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          {/* F6 replaces this placeholder with the run detail page. */}
          <Route path="/runs/:id" element={<PlaceholderPage section="runs" />} />
          {NAV_ITEMS.filter(
            (item) => !["connections", "resources", "mappings", "jobs"].includes(item.key),
          ).map((item) => (
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
