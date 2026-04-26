import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import WorkspaceRoute from "./workspace";

const FAKE_SESSION = {
  id: "abc1234567",
  project_id: "p1",
  name: "test session",
  model_name: null,
  use_negative: true,
  pinned_loras: [] as { lora_name: string; weight_override: number | null }[],
  source_image_path: null,
  source_image_url: null,
  vl_summary: null,
  vl_model_name: null,
  prompt_model_name: null,
  created_at: 1,
  updated_at: 1,
};

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

describe("workspace route", () => {
  it("renders header, source drop zone, and pane placeholders", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      const s = String(url);
      if (s.endsWith("/api/projects")) {
        return json([{ id: "p1", name: "Test", session_count: 1, created_at: 1, updated_at: 1 }]);
      }
      if (s.includes("/api/sessions/") && s.endsWith("/messages")) {
        return json({ messages: [] });
      }
      if (s.includes("/api/sessions/") && s.includes(FAKE_SESSION.id)) {
        return json(FAKE_SESSION);
      }
      if (s.includes("/api/library/models")) return json([]);
      if (s.includes("/api/library/loras")) return json([]);
      return json([]);
    }));

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/projects/p1/sessions/${FAKE_SESSION.id}`]}>
          <Routes>
            <Route
              path="/projects/:projectId/sessions/:sessionId"
              element={<WorkspaceRoute />}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText("test session")).toBeInTheDocument());
    expect(screen.getByText(/Drop source image/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate prompt/i })).toBeInTheDocument();
    expect(screen.getByText(/Prompt pane/)).toBeInTheDocument();
  });
});
