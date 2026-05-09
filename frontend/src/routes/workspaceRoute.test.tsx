import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import WorkspaceRoute from "./workspace";

const FAKE_SESSION = {
  id: "abc1234567",
  project_id: "p1",
  name: "test session",
  session_type: "i2i" as const,
  model_name: null,
  use_negative: true,
  pinned_loras: [] as { lora_name: string; weight_override: number | null }[],
  source_images: [] as Array<{
    id: string;
    session_id: string;
    path: string;
    url: string;
    original_filename: string;
    is_main: boolean;
    analysis: string | null;
    analysis_prompt: string | null;
    created_at: number;
    updated_at: number;
  }>,
  vl_model_name: null,
  prompt_model_name: null,
  comfy_input_cleanup: "keep" as const,
  comfy_restart_after_run: false,
  hidden: false,
  created_at: 1,
  updated_at: 1,
};

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

type FakeSession = Omit<typeof FAKE_SESSION, "session_type"> & {
  session_type: "i2i" | "t2i" | "comfy";
};

function stubFetchFor(session: FakeSession) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const s = String(url);
      if (s.endsWith("/api/projects")) {
        return json([
          { id: "p1", name: "Test", session_count: 1, created_at: 1, updated_at: 1 },
        ]);
      }
      if (s.includes("/api/sessions/") && s.endsWith("/messages")) {
        return json({ messages: [] });
      }
      if (s.includes("/api/sessions/") && s.includes(session.id)) {
        return json(session);
      }
      if (s.includes("/api/library/models")) return json([]);
      if (s.includes("/api/library/loras")) return json([]);
      if (s.includes("/api/sessions/") && s.endsWith("/prompts")) return json({ prompts: [] });
      if (s.includes("/api/comfy/sessions/") && s.endsWith("/readiness")) {
        return json({ ready: false, cards: [], error: null });
      }
      return json([]);
    }),
  );
}

function renderRoute(session: FakeSession) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/projects/p1/sessions/${session.id}`]}>
        <Routes>
          <Route
            path="/projects/:projectId/sessions/:sessionId"
            element={<WorkspaceRoute />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("workspace route dispatch", () => {
  it("dispatches i2i sessions to the i2i workspace (sources | chat | prompt)", async () => {
    stubFetchFor(FAKE_SESSION);
    renderRoute(FAKE_SESSION);

    await waitFor(() => expect(screen.getByText("test session")).toBeInTheDocument());
    expect(screen.getByText(/Drop source images/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByLabelText(/prompt pane/i)).toBeInTheDocument();
  });

  it("dispatches t2i sessions to the t2i workspace (sources | chat | prompt)", async () => {
    const session = { ...FAKE_SESSION, session_type: "t2i" as const };
    stubFetchFor(session);
    renderRoute(session);

    await waitFor(() => expect(screen.getByText("test session")).toBeInTheDocument());
    expect(screen.getByText(/Drop reference images/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByLabelText(/prompt pane/i)).toBeInTheDocument();
  });

  it("dispatches comfy sessions to the comfy workspace (readiness gate first)", async () => {
    const session = { ...FAKE_SESSION, session_type: "comfy" as const };
    stubFetchFor(session);
    renderRoute(session);

    await waitFor(() => expect(screen.getByText("test session")).toBeInTheDocument());
    // Comfy starts on the readiness step — no source/prompt panes yet.
    expect(screen.queryByText(/Drop reference images/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/prompt pane/i)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Workflow readiness/i)).toBeInTheDocument(),
    );
  });
});
