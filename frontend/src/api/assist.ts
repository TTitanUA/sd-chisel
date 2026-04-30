import { API_BASE, ApiError } from "./client";

export type AssistantMessage = {
  role: "user" | "assistant";
  content: string;
};

export type AssistStreamEvent =
  | { type: "delta"; content: string }
  | { type: "artifact"; content: string }
  | { type: "done" }
  | { type: "error"; detail: string };

export type AssistStreamCallbacks = {
  onDelta: (chunk: string) => void;
  onArtifact: (content: string) => void;
  onDone: () => void;
  onError: (detail: string) => void;
};

export async function streamAssist(
  model: string,
  messages: AssistantMessage[],
  cb: AssistStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/library/families/assist`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ model, messages }),
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
  for (;;) {
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
      let evt: AssistStreamEvent;
      try {
        evt = JSON.parse(data) as AssistStreamEvent;
      } catch {
        continue;
      }
      if (evt.type === "delta") cb.onDelta(evt.content);
      else if (evt.type === "artifact") cb.onArtifact(evt.content);
      else if (evt.type === "done") cb.onDone();
      else if (evt.type === "error") cb.onError(evt.detail);
    }
  }
}
