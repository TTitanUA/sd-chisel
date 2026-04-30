import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { streamAssist, type AssistFieldName, type AssistFieldsSnapshot } from "@/api/assist";
import { useLmModels } from "@/api/settings";
import styles from "./AssistantPane.module.css";

type ChatEntry = { role: "user" | "assistant"; content: string };

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
const SEND_HINT = isMac ? "⌘↵ to send" : "Ctrl↵ to send";

const TOOL_LABELS: Record<string, string> = {
  update_prompt_guide: "updating base guide",
  update_prompt_i2i: "updating i2i guide",
  update_prompt_t2i: "updating t2i guide",
};

// Collapse model-emitted whitespace runs (reasoning padding, blank deltas
// around tool calls, post-function-call continuations, etc.) so the chat
// bubble doesn't grow into a tall empty box.
function normalizeAssistantText(raw: string): string {
  return raw.replace(/\n{3,}/g, "\n\n").trim();
}

export function AssistantPane({
  getCurrentState,
  onArtifact,
}: {
  getCurrentState: () => AssistFieldsSnapshot;
  onArtifact: (field: AssistFieldName, content: string) => void;
}) {
  const allModels = useLmModels();
  const toolModels = useMemo(
    () => (allModels.data ?? []).filter((m) => m.enabled && m.tool_use),
    [allModels.data],
  );

  const [model, setModel] = useState("");
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [currentTool, setCurrentTool] = useState<string | null>(null);
  const [toolCount, setToolCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [responseId, setResponseId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!model && toolModels.length > 0) {
      const favorite = toolModels.find((m) => m.favorite);
      setModel((favorite ?? toolModels[0]).name);
    }
  }, [model, toolModels]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight });
  }, [messages.length, streaming]);

  async function send() {
    const content = draft.trim();
    if (!content || pending || !model) return;

    setMessages((prev) => [...prev, { role: "user", content }]);
    setDraft("");
    setStreaming("");
    setCurrentTool(null);
    setToolCount(0);
    setError(null);
    setPending(true);

    const snapshot = getCurrentState();
    let assistantText = "";
    try {
      await streamAssist(model, content, responseId, snapshot, {
        onDelta: (chunk) => {
          assistantText += chunk;
          setStreaming(assistantText);
        },
        onArtifact: (field, artifactContent) => {
          onArtifact(field, artifactContent);
        },
        onToolStatus: (tool, status) => {
          if (status === "running") {
            setCurrentTool(tool || "tool");
          } else {
            setCurrentTool(null);
            if (status === "done" || status === "failed") {
              setToolCount((n) => n + 1);
            }
          }
        },
        onDone: (rid) => {
          if (rid) setResponseId(rid);
        },
        onError: (detail) => setError(detail),
      });
    } catch (err) {
      setError(String(err));
    } finally {
      const cleaned = normalizeAssistantText(assistantText);
      if (cleaned) {
        setMessages((prev) => [...prev, { role: "assistant", content: cleaned }]);
      }
      setPending(false);
      setStreaming("");
      setCurrentTool(null);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  }

  const streamingDisplay = pending ? normalizeAssistantText(streaming) : "";
  const showThinking = pending && streamingDisplay.length === 0 && !currentTool;
  const showStreaming = pending && streamingDisplay.length > 0;
  const toolLabel = currentTool
    ? (TOOL_LABELS[currentTool] ?? `running ${currentTool}…`)
    : "";
  const statusLabel = currentTool
    ? toolLabel
    : showStreaming
      ? "writing reply…"
      : "thinking…";

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Assistant</span>
        <div className={styles.spacer} />
        <select
          className={styles.modelSelect}
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            setResponseId(null);
          }}
          disabled={pending}
        >
          {toolModels.length === 0 && <option value="">No tool_use models</option>}
          {toolModels.map((m) => (
            <option key={m.name} value={m.name}>{m.name}</option>
          ))}
        </select>
      </div>
      <div className={styles.body}>
        {pending && (
          <div className={styles.statusBar} role="status" aria-live="polite">
            <span className={styles.statusDot} />
            <span className={styles.statusLabel}>{statusLabel}</span>
            <span className={styles.statusSpacer} />
            <span className={styles.statusCount}>
              {toolCount === 1 ? "1 tool used" : `${toolCount} tools used`}
            </span>
          </div>
        )}
        <div className={styles.scroll} ref={scrollRef}>
          {messages.length === 0 && !pending && (
            <div className={styles.empty}>
              Paste documentation or describe the model family to get started.
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} role={m.role} content={m.content} />
          ))}
          {showStreaming && <Bubble role="assistant" content={streamingDisplay} streaming />}
          {showThinking && <ThinkingBubble />}
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        <div className={styles.composer}>
          <textarea
            className={styles.textarea}
            placeholder="Describe the family or paste docs…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={pending}
          />
          <div className={styles.composerRow}>
            <span className={styles.hint}>{SEND_HINT}</span>
            <div className={styles.spacer} />
            <Button
              size="sm"
              variant="primary"
              icon={<Icon name="Send" size={12} />}
              onClick={() => void send()}
              disabled={pending || draft.trim().length === 0 || !model}
            >
              {pending ? "Sending…" : "Send"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bubble({
  role,
  content,
  streaming = false,
}: {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}) {
  const variantClass = role === "user" ? "ds-chat-user" : "ds-chat-assistant";
  return (
    <div className={`ds-chat ${variantClass}`}>
      {role !== "user" && (
        <div className="ds-chat-avatar" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
          </svg>
        </div>
      )}
      <div className="ds-chat-body">
        <div className="ds-chat-meta">
          {role === "user" ? "You" : "Assistant"}
        </div>
        <div className={styles.msgContent}>
          {content}
          {streaming && <span className="ds-chat-cursor" />}
        </div>
      </div>
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="ds-chat ds-chat-assistant">
      <div className="ds-chat-avatar" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
        </svg>
      </div>
      <div className="ds-chat-body">
        <div className="ds-chat-meta">Assistant · thinking</div>
        <div className={styles.typing}>
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
