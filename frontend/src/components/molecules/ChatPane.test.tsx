import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPane } from "./ChatPane";
import type { Session } from "@/api/sessions";

const SESSION: Session = {
  id: "s1",
  project_id: "p1",
  name: "demo",
  session_type: "i2i",
  model_name: null,
  use_negative: true,
  pinned_loras: [],
  source_images: [],
  vl_model_name: null,
  prompt_model_name: "mistral",
  comfy_input_cleanup: "keep",
  hidden: false,
  created_at: 0,
  updated_at: 0,
};

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

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatPane", () => {
  it("renders empty state with Send button only — no in-pane Generate button", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/messages")) return jsonResponse({ messages: [] });
      throw new Error(`unexpected fetch: ${url}`);
    }));

    render(withClient(<ChatPane session={SESSION} />));
    await waitFor(() => expect(screen.getByRole("textbox")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^send$/i })).toBeInTheDocument();
    // The duplicate "Generate prompt" trigger that used to live in the
    // composer row was removed — generation is launched either by the
    // chat tool flow or by the Regenerate button in PromptPane.
    expect(screen.queryByRole("button", { name: /generate prompt/i })).toBeNull();
  });

  it("streams assistant deltas and refetches history on done", async () => {
    let messagesCallCount = 0;
    const initialMsgs = { messages: [] as unknown[] };
    const finalMsgs = {
      messages: [
        { id: 1, session_id: "s1", role: "user", content: "hi", created_at: 1 },
        { id: 2, session_id: "s1", role: "assistant", content: "hello there", created_at: 2 },
      ],
    };

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/messages")) {
        messagesCallCount += 1;
        return jsonResponse(messagesCallCount === 1 ? initialMsgs : finalMsgs);
      }
      if (url.endsWith("/chat") && init?.method === "POST") {
        return makeStreamResponse([
          'data: {"type":"delta","content":"hello "}\n\n',
          'data: {"type":"delta","content":"there"}\n\n',
          'data: {"type":"done","message_id":2}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    render(withClient(<ChatPane session={SESSION} />));
    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "hi");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    // optimistic user message visible immediately
    expect(await screen.findByText("hi")).toBeInTheDocument();

    // assistant streamed content visible during stream
    await waitFor(() => expect(screen.getByText(/hello there/)).toBeInTheDocument());

    // history refetched at least once after done
    await waitFor(() => expect(messagesCallCount).toBeGreaterThanOrEqual(2));
  });

  it("disables send while in flight and shows error event", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/messages")) return jsonResponse({ messages: [] });
      if (url.endsWith("/chat") && init?.method === "POST") {
        return makeStreamResponse([
          'data: {"type":"error","detail":"upstream blew up"}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    render(withClient(<ChatPane session={SESSION} />));
    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "hi");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/upstream blew up/);
  });
});
