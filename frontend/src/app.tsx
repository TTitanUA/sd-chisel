import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { queryClient } from "./api/client";
import { AppShell } from "./components/templates/AppShell";
import { WorkspaceLayout } from "./components/templates/WorkspaceLayout";
import { LibraryLayout } from "./components/templates/LibraryLayout";
import WorkspaceRoute from "./routes/workspace";
import FamiliesRoute from "./routes/library/families";
import ModelsRoute from "./routes/library/models";
import LorasRoute from "./routes/library/loras";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route
              path="/"
              element={<Navigate to="/projects/scrapyard/sessions/default" replace />}
            />
            <Route
              path="/projects/:projectId/sessions/:sessionId"
              element={
                <WorkspaceLayout>
                  <WorkspaceRoute />
                </WorkspaceLayout>
              }
            />
            <Route
              path="/library/families"
              element={
                <LibraryLayout>
                  <FamiliesRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/models"
              element={
                <LibraryLayout>
                  <ModelsRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/loras"
              element={
                <LibraryLayout>
                  <LorasRoute />
                </LibraryLayout>
              }
            />
            <Route path="*" element={<div style={{ padding: 24 }}>404</div>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
