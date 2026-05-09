import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Session } from "@/api/sessions";
import { I2iWorkspace } from "./I2iWorkspace";

const SESSION: Session = {
  id: "i2i-session",
  project_id: "p1",
  name: "i2i smoke",
  session_type: "i2i",
  model_name: null,
  use_negative: true,
  pinned_loras: [],
  source_images: [],
  vl_model_name: null,
  prompt_model_name: null,
  comfy_input_cleanup: "keep",
  comfy_restart_after_run: false,
  hidden: false,
  created_at: 1,
  updated_at: 1,
};

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

describe("I2iWorkspace", () => {
  it("renders the source-drop zone, chat textbox, and prompt pane", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const s = String(url);
        if (s.endsWith("/api/projects")) {
          return json([
            { id: "p1", name: "Test", session_count: 1, created_at: 1, updated_at: 1 },
          ]);
        }
        if (s.includes("/messages")) return json({ messages: [] });
        if (s.includes("/prompts")) return json({ prompts: [] });
        if (s.includes("/library")) return json([]);
        return json([]);
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <I2iWorkspace session={SESSION} projectId="p1" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("i2i smoke")).toBeInTheDocument());
    expect(screen.getByText(/Drop source images/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByLabelText(/prompt pane/i)).toBeInTheDocument();
  });
});
