/** Chat panel — reference-only. The emulator echoes user messages
 *  back; layout is the only thing being tested. See
 *  docs/comfy-agents-ui-mock-plan.md. */
import { useEffect, useRef, useState } from "react";
import { useComfyMock } from "../state/useComfyMock";
import styles from "./ChatPanel.module.css";

export function ChatPanel() {
  const { chat, sendChat, clearChat } = useComfyMock();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [chat]);

  const send = async () => {
    if (!draft.trim() || pending) return;
    const text = draft;
    setDraft("");
    setPending(true);
    try {
      await sendChat(text);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>Chat (reference-only)</span>
        <button
          type="button"
          className={styles.clear}
          onClick={clearChat}
          disabled={chat.length === 0}
        >
          clear
        </button>
      </div>
      <div className={styles.messages} ref={scrollRef}>
        {chat.length === 0 && (
          <div className={styles.empty}>
            No messages yet. The chat is reference-only — anything you write
            here doesn&rsquo;t feed an agent.
          </div>
        )}
        {chat.map((m) => (
          <div
            key={m.id}
            className={`${styles.message} ${
              m.role === "user" ? styles.user : styles.assistant
            }`}
          >
            <span className={styles.role}>{m.role}</span>
            <span className={styles.content}>{m.content}</span>
          </div>
        ))}
        {pending && (
          <div className={`${styles.message} ${styles.assistant}`}>
            <span className={styles.role}>assistant</span>
            <span className={styles.content}>thinking…</span>
          </div>
        )}
      </div>
      <div className={styles.composer}>
        <input
          className={styles.input}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask about the workflow…"
        />
        <button
          type="button"
          className={styles.send}
          onClick={send}
          disabled={!draft.trim() || pending}
        >
          Send
        </button>
      </div>
    </div>
  );
}
