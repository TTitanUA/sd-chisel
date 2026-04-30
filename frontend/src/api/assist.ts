import { API_BASE, ApiError } from "./client";

export type AssistFieldName = "prompt_guide" | "prompt_i2i" | "prompt_t2i";

export type AssistFieldsSnapshot = {
  prompt_guide: string;
  prompt_i2i: string;
  prompt_t2i: string;
};

export type AssistStreamEvent =
  | { type: "delta"; content: string }
  | { type: "artifact"; field: AssistFieldName; content: string }
  | { type: "tool_status"; tool: string; status: string }
  | { type: "done"; response_id: string }
  | { type: "error"; detail: string };

export type AssistStreamCallbacks = {
  onDelta: (chunk: string) => void;
  onArtifact: (field: AssistFieldName, content: string) => void;
  onToolStatus?: (tool: string, status: string) => void;
  onDone: (responseId: string) => void;
  onError: (detail: string) => void;
};

export async function streamAssist(
  model: string,
  message: string,
  previousResponseId: string | null,
  currentState: AssistFieldsSnapshot,
  cb: AssistStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const body: Record<string, unknown> = {
    model,
    message,
    current_state: currentState,
  };
  if (previousResponseId) body.previous_response_id = previousResponseId;

  const res = await fetch(`${API_BASE}/api/library/families/assist`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
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
      else if (evt.type === "artifact") cb.onArtifact(evt.field, evt.content);
      else if (evt.type === "tool_status") cb.onToolStatus?.(evt.tool, evt.status);
      else if (evt.type === "done") cb.onDone(evt.response_id);
      else if (evt.type === "error") cb.onError(evt.detail);
    }
  }
}
