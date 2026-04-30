import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantPane } from "./AssistantPane";

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
    render(withClient(<AssistantPane onArtifact={onArtifact} />));

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
          'data: {"type":"artifact","content":"# My Guide"}\n\n',
          'data: {"type":"done"}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const onArtifact = vi.fn();
    render(withClient(<AssistantPane onArtifact={onArtifact} />));

    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "help me");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => expect(onArtifact).toHaveBeenCalledWith("# My Guide"));
    await waitFor(() => expect(screen.getByText(/here is a guide/i)).toBeInTheDocument());
  });
});
