import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  streamChat,
  useChatInvalidation,
  useMessages,
  type ChatMessage,
} from "@/api/chat";
import type { Session } from "@/api/sessions";
import { useGeneratePrompt } from "@/api/prompts";
import { useIsReindexing } from "@/api/tasks";
import styles from "./ChatPane.module.css";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
const SEND_HINT = isMac ? "⌘↵ to send" : "Ctrl↵ to send";

export function ChatPane({ session }: { session: Session }) {
  const messages = useMessages(session.id);
  const generate = useGeneratePrompt(session.id);
  const invalidate = useChatInvalidation();
  const isReindexing = useIsReindexing();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [optimistic, setOptimistic] = useState<ChatMessage | null>(null);
  const [streaming, setStreaming] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const rows = messages.data ?? [];
  const showOptimistic = optimistic && !rows.some((r) => r.id === optimistic.id);
  const showStreamingThinking = pending && streaming.length === 0;
  const showStreamingBubble = pending && streaming.length > 0;
  const totalCount = rows.length + (showOptimistic ? 1 : 0);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [rows.length, streaming, optimistic?.id, showStreamingThinking]);

  async function send() {
    const content = draft.trim();
    if (!content || pending) return;
    const tempUser: ChatMessage = {
      id: -Date.now(),
      session_id: session.id,
      role: "user",
      content,
      created_at: Math.floor(Date.now() / 1000),
    };
    setOptimistic(tempUser);
    setStreaming("");
    setDraft("");
    setError(null);
    setPending(true);
    try {
      await streamChat(session.id, content, {
        onDelta: (chunk) => setStreaming((s) => s + chunk),
        onDone: () => {
          invalidate.messages(session.id);
        },
        onError: (detail) => setError(detail),
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setPending(false);
      setStreaming("");
      setOptimistic(null);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Chat</span>
        <span className={styles.sub}>· {totalCount} msg</span>
        <div className={styles.spacer} />
        <span
          className={styles.subTrunc}
          title={session.prompt_model_name ?? "Prompt model used for this session"}
        >
          {session.prompt_model_name ?? "(no model)"}
        </span>
      </div>
      <div className={styles.body}>
        <div className={styles.scroll} ref={scrollRef}>
          {rows.length === 0 && !showOptimistic && !showStreamingThinking && !showStreamingBubble && (
            <div className={styles.empty}>
              {session.source_image_path
                ? <>Describe the change you want. I&rsquo;ll pick LoRAs from your library and assemble a prompt.</>
                : <>Add a source image first &mdash; I need a VL summary to anchor the prompt.</>}
            </div>
          )}
          {rows.map((m) => (
            <Bubble key={m.id} role={m.role} content={m.content} createdAt={m.created_at} />
          ))}
          {showOptimistic && optimistic && (
            <Bubble role={optimistic.role} content={optimistic.content} createdAt={optimistic.created_at} />
          )}
          {showStreamingBubble && (
            <Bubble role="assistant" content={streaming} createdAt={Math.floor(Date.now() / 1000)} streaming />
          )}
          {showStreamingThinking && <ThinkingBubble />}
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        <div className={styles.composer}>
          <textarea
            className={styles.textarea}
            placeholder={
              session.source_image_path
                ? "Describe the change…"
                : "Add source image first"
            }
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
              icon={<Icon name="Sparkles" size={12} />}
              onClick={() => generate.mutate()}
              disabled={generate.isPending || !session.vl_summary || isReindexing}
              title={
                !session.vl_summary
                  ? "Run Analyze on the source image first"
                  : isReindexing
                    ? "LoRA index is updating — try again in a moment"
                    : "Generate prompt"
              }
            >
              {generate.isPending ? "Generating…" : "Generate prompt"}
            </Button>
            <Button
              size="sm"
              variant="primary"
              icon={<Icon name="Send" size={12} />}
              onClick={() => void send()}
              disabled={pending || draft.trim().length === 0}
            >
              {pending ? "Sending…" : "Send"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatTime(unixSeconds: number): string {
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Bubble({
  role,
  content,
  createdAt,
  streaming = false,
}: {
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: number;
  streaming?: boolean;
}) {
  const time = useMemo(() => formatTime(createdAt), [createdAt]);
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
          {role === "user" ? "You" : "sd-chisel"} · {time}
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
        <div className="ds-chat-meta">sd-chisel · thinking</div>
        <div className={styles.typing}>
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
