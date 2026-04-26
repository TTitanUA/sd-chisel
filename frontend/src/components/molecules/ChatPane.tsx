import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  streamChat,
  useChatInvalidation,
  useMessages,
  type ChatMessage,
} from "@/api/chat";
import type { Session } from "@/api/sessions";
import styles from "./ChatPane.module.css";

export function ChatPane({ session }: { session: Session }) {
  const messages = useMessages(session.id);
  const invalidate = useChatInvalidation();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [optimistic, setOptimistic] = useState<ChatMessage | null>(null);
  const [streaming, setStreaming] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  const rows = messages.data ?? [];
  const showOptimistic = optimistic && !rows.some((r) => r.id === optimistic.id);
  const showStreaming = pending && streaming.length > 0;

  useEffect(() => {
    const el = bodyRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [rows.length, streaming, optimistic?.id]);

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
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Chat</span>
        <span>· prompt model: {session.prompt_model_name ?? "(not set)"}</span>
      </div>
      <div className={styles.body} ref={bodyRef}>
        {rows.length === 0 && !showOptimistic && !showStreaming && (
          <div className={styles.empty}>No messages yet. Say hi.</div>
        )}
        {rows.map((m) => (
          <div key={m.id} className={styles.msg}>
            <span className={styles.role}>{m.role}</span>
            <div className={m.role === "user" ? styles.user : styles.assistant}>
              {m.content}
            </div>
          </div>
        ))}
        {showOptimistic && optimistic && (
          <div className={styles.msg}>
            <span className={styles.role}>{optimistic.role}</span>
            <div className={styles.user}>{optimistic.content}</div>
          </div>
        )}
        {showStreaming && (
          <div className={styles.msg}>
            <span className={styles.role}>assistant</span>
            <div className={styles.assistant}>{streaming}</div>
          </div>
        )}
      </div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.composer}>
        <textarea
          className={styles.input}
          placeholder="Message…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          disabled={pending}
        />
        <Button
          size="sm"
          variant="primary"
          icon={<Icon name="Send" size={12} />}
          onClick={() => void send()}
          disabled={pending || draft.trim().length === 0}
        >
          {pending ? "Sending…" : "Send"}
        </Button>
        <Button
          size="sm"
          icon={<Icon name="Sparkles" size={12} />}
          disabled
          title="Generate prompt — available in Slice 6"
        >
          Generate prompt
        </Button>
      </div>
    </div>
  );
}
