import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { queryClient } from "./api/client";
import { useProjects } from "./api/sessions";
import { AppShell } from "./components/templates/AppShell";
import { WorkspaceLayout } from "./components/templates/WorkspaceLayout";
import { LibraryLayout } from "./components/templates/LibraryLayout";
import { SettingsLayout } from "./components/templates/SettingsLayout";
import WorkspaceRoute, { ProjectLanding } from "./routes/workspace";
import NewSessionRoute from "./routes/newSession";
import FamiliesRoute from "./routes/library/families";
import ModelsRoute from "./routes/library/models";
import LorasRoute from "./routes/library/loras";
import ComfyNodesRoute from "./routes/library/comfyNodes";
import LmStudioRoute from "./routes/settings/lmstudio";
import ComfyUiRoute from "./routes/settings/comfyui";
import PrivacyRoute from "./routes/settings/privacy";

function RootRedirect() {
  const projects = useProjects();
  if (projects.isLoading) return <div style={{ padding: 24 }}>Loading…</div>;
  const first = projects.data?.[0];
  if (!first) {
    return (
      <div style={{ padding: 24 }}>
        No projects yet. Use the sidebar to create one.
      </div>
    );
  }
  return <Navigate to={`/projects/${first.id}`} replace />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<RootRedirect />} />
            <Route
              path="/projects/:projectId"
              element={
                <WorkspaceLayout>
                  <ProjectLanding />
                </WorkspaceLayout>
              }
            />
            <Route
              path="/projects/:projectId/sessions/new"
              element={
                <WorkspaceLayout>
                  <NewSessionRoute />
                </WorkspaceLayout>
              }
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
              path="/library/families/*"
              element={
                <LibraryLayout>
                  <FamiliesRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/models/*"
              element={
                <LibraryLayout>
                  <ModelsRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/loras/*"
              element={
                <LibraryLayout>
                  <LorasRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/comfy-nodes/*"
              element={
                <LibraryLayout>
                  <ComfyNodesRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/settings"
              element={<Navigate to="/settings/lmstudio" replace />}
            />
            <Route
              path="/settings/lmstudio"
              element={
                <SettingsLayout>
                  <LmStudioRoute />
                </SettingsLayout>
              }
            />
            <Route
              path="/settings/comfyui"
              element={
                <SettingsLayout>
                  <ComfyUiRoute />
                </SettingsLayout>
              }
            />
            <Route
              path="/settings/privacy"
              element={
                <SettingsLayout>
                  <PrivacyRoute />
                </SettingsLayout>
              }
            />
            <Route path="*" element={<div style={{ padding: 24 }}>404</div>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
