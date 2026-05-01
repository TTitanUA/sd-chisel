import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantPane } from "./AssistantPane";
import { streamAssist, type AssistStreamCallbacks } from "@/api/assist";

function makeStreamResponse(events: string[]) {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const e of events) controller.enqueue(enc.encode(e));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

const MODELS_RESPONSE = {
  models: [
    { name: "tool-model", vision: false, tool_use: true, reasoning: false, enabled: true, last_seen: 1 },
    { name: "no-tools", vision: false, tool_use: false, reasoning: false, enabled: true, last_seen: 1 },
  ],
};

const FAMILY_TOOL_LABELS: Record<string, string> = {
  update_prompt_guide: "updating base guide",
  update_prompt_i2i: "updating i2i guide",
  update_prompt_t2i: "updating t2i guide",
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AssistantPane", () => {
  it("renders empty state and model selector with tool_use models only", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/lmstudio/models")) return jsonResponse(MODELS_RESPONSE);
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const onArtifact = vi.fn();
    const getCurrentState = () => ({ prompt_guide: "", prompt_i2i: "", prompt_t2i: "" });
    render(withClient(
      <AssistantPane
        getCurrentState={getCurrentState}
        onArtifact={onArtifact}
        streamFn={streamAssist}
        toolLabels={FAMILY_TOOL_LABELS}
      />,
    ));

    await waitFor(() => expect(screen.getByText(/paste documentation/i)).toBeInTheDocument());
    const select = screen.getByRole("combobox");
    await waitFor(() => {
      const options = Array.from(select.querySelectorAll("option"));
      expect(options.map((o) => o.value)).toEqual(["tool-model"]);
    });
  });

  it("sends message and calls onArtifact when artifact event received", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/lmstudio/models")) return jsonResponse(MODELS_RESPONSE);
      if (url.includes("/families/assist") && init?.method === "POST") {
        return makeStreamResponse([
          'data: {"type":"delta","content":"Here is a guide."}\n\n',
          'data: {"type":"artifact","field":"prompt_guide","content":"# My Guide"}\n\n',
          'data: {"type":"done","response_id":"resp_1"}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const onArtifact = vi.fn();
    const getCurrentState = () => ({ prompt_guide: "", prompt_i2i: "", prompt_t2i: "" });
    render(withClient(
      <AssistantPane
        getCurrentState={getCurrentState}
        onArtifact={onArtifact}
        streamFn={streamAssist}
        toolLabels={FAMILY_TOOL_LABELS}
      />,
    ));

    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "help me");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => expect(onArtifact).toHaveBeenCalledWith("prompt_guide", "# My Guide"));
    await waitFor(() => expect(screen.getByText(/here is a guide/i)).toBeInTheDocument());
  });

  it("works with a custom streamFn (LoRA-style)", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/lmstudio/models")) return jsonResponse(MODELS_RESPONSE);
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const onArtifact = vi.fn();
    const getCurrentState = () => ({ description: "", tags: [], trigger_words: [] });

    const fakeStream = vi.fn(async (
      _model: string, _msg: string, _prev: string | null,
      _state: unknown, cb: AssistStreamCallbacks,
    ) => {
      cb.onDelta("Done.");
      cb.onArtifact("description", "# LoRA desc");
      cb.onArtifact("tags", '["style","anime"]');
      cb.onDone("resp_2");
    });

    render(withClient(
      <AssistantPane
        getCurrentState={getCurrentState}
        onArtifact={onArtifact}
        streamFn={fakeStream}
        toolLabels={{ update_description: "updating description" }}
        emptyMessage="Describe the LoRA."
      />,
    ));

    await waitFor(() => expect(screen.getByText("Describe the LoRA.")).toBeInTheDocument());

    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "fill it");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => {
      expect(onArtifact).toHaveBeenCalledWith("description", "# LoRA desc");
      expect(onArtifact).toHaveBeenCalledWith("tags", '["style","anime"]');
    });
  });
});
