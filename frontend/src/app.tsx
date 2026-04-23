import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { queryClient } from "./api/client";
import WorkspaceRoute from "./routes/workspace";
import FamiliesRoute from "./routes/library/families";
import ModelsRoute from "./routes/library/models";
import LorasRoute from "./routes/library/loras";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/projects/scrapyard/sessions/default" replace />} />
          <Route path="/projects/:projectId/sessions/:sessionId" element={<WorkspaceRoute />} />
          <Route path="/library/families" element={<FamiliesRoute />} />
          <Route path="/library/models" element={<ModelsRoute />} />
          <Route path="/library/loras" element={<LorasRoute />} />
          <Route path="*" element={<div>404</div>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
