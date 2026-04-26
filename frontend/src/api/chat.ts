import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, ApiError, apiFetch } from "./client";

export type ChatMessage = {
  id: number;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: number;
};

export type ChatStreamEvent =
  | { type: "delta"; content: string }
  | { type: "done"; message_id: number }
  | { type: "error"; detail: string };

export const chatKeys = {
  messages: (sessionId: string) => ["sessions", sessionId, "messages"] as const,
};

export const chatApi = {
  listMessages: (sessionId: string) =>
    apiFetch<{ messages: ChatMessage[] }>(`/api/sessions/${sessionId}/messages`),
};

export function useMessages(sessionId: string | undefined) {
  return useQuery({
    enabled: !!sessionId,
    queryKey: sessionId ? chatKeys.messages(sessionId) : ["sessions", "__noop", "messages"],
    queryFn: async () => (await chatApi.listMessages(sessionId as string)).messages,
  });
}

export function useChatInvalidation() {
  const client = useQueryClient();
  return {
    messages: (sessionId: string) =>
      void client.invalidateQueries({ queryKey: chatKeys.messages(sessionId) }),
  };
}

export type StreamCallbacks = {
  onDelta: (chunk: string) => void;
  onDone: (messageId: number) => void;
  onError: (detail: string) => void;
};

/**
 * POST a chat turn and parse the SSE response into typed callbacks.
 * Resolves once the stream closes (success OR error). Does NOT throw on
 * application-level errors — callers handle them via onError.
 */
export async function streamChat(
  sessionId: string,
  content: string,
  cb: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  const reader = res.body?.getReader();
  if (!reader) {
    cb.onError("no response body");
    return;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = raw.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const data = line.slice("data:".length).trim();
      if (!data) continue;
      let evt: ChatStreamEvent;
      try {
        evt = JSON.parse(data) as ChatStreamEvent;
      } catch {
        continue;
      }
      if (evt.type === "delta") cb.onDelta(evt.content);
      else if (evt.type === "done") cb.onDone(evt.message_id);
      else if (evt.type === "error") cb.onError(evt.detail);
    }
  }
}
