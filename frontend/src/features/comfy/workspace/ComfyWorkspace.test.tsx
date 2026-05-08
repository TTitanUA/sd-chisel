import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Session } from "@/api/sessions";
import { ComfyWorkspace } from "./ComfyWorkspace";

const SESSION: Session = {
  id: "comfy-session",
  project_id: "p1",
  name: "comfy smoke",
  session_type: "comfy",
  model_name: null,
  use_negative: false,
  pinned_loras: [],
  source_images: [],
  vl_model_name: null,
  prompt_model_name: null,
  comfy_input_cleanup: "keep",
  hidden: false,
  created_at: 1,
  updated_at: 1,
};

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

function stubFetch({ ready }: { ready: boolean }) {
  return vi.fn((url: string) => {
    const s = String(url);
    if (s.endsWith("/api/projects")) {
      return json([
        { id: "p1", name: "Test", session_count: 1, created_at: 1, updated_at: 1 },
      ]);
    }
    if (s.includes("/api/comfy/sessions/") && s.endsWith("/readiness")) {
      return json({
        session_id: SESSION.id,
        workflow_id: "wf1",
        ready,
        cards: ready
          ? [
              {
                class_type: "KSampler",
                status: "ready",
                instance_count: 1,
                display_name: "KSampler",
                description: null,
                category: null,
                python_module: null,
                pack_name: null,
              },
            ]
          : [],
        error: null,
      });
    }
    if (s.includes("/api/comfy/sessions/") && s.endsWith("/slot_map")) {
      return json({
        session_id: SESSION.id,
        workflow_id: "wf1",
        slot_map: {
          version: 2,
          slots: [
            {
              label: "subject",
              group: "prompt",
              ordinal: 1,
              description: null,
              kind: "multiline_text",
              origin: { node_id: "1", input_name: "text" },
              binding: "llm",
              metadata: {},
            },
          ],
        },
        candidates: {
          text: [],
          multiline_text: [],
          image: [],
          image_alpha: [],
          number_int: [],
          number_float: [],
          boolean: [],
          enum: [],
          lora_name: [],
          checkpoint_name: [],
        },
        inferred_mode: "t2i",
      });
    }
    if (s.includes("/api/comfy/sessions/") && s.endsWith("/agents")) {
      return json({ agents: [] });
    }
    if (s.includes("/messages")) return json({ messages: [] });
    if (s.includes("/prompts")) return json({ prompts: [] });
    if (s.includes("/library")) return json([]);
    return json([]);
  });
}

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ComfyWorkspace session={SESSION} projectId="p1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ComfyWorkspace", () => {
  it("opens on the readiness gate when readiness is not ready", async () => {
    vi.stubGlobal("fetch", stubFetch({ ready: false }));
    renderWorkspace();
    await waitFor(() => expect(screen.getByText("comfy smoke")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByText(/Workflow readiness/i)).toBeInTheDocument(),
    );
  });

  it("renders the IDE-like layout when ready (left tab bar + mode toggle)", async () => {
    vi.stubGlobal("fetch", stubFetch({ ready: true }));
    renderWorkspace();
    await waitFor(() => expect(screen.getByText("comfy smoke")).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Generate workflow/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /Agent editor/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Node tree/i })).toBeInTheDocument();
    expect(screen.getByTitle("Agents")).toBeInTheDocument();
    expect(screen.getByTitle("Chat")).toBeInTheDocument();
  });
});
