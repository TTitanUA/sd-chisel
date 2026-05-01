import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  streamChat,
  useChatInvalidation,
  useMessages,
  type ChatMessage,
} from "@/api/chat";
import { imageDisplayName, type Session, type SourceImage } from "@/api/sessions";
import {
  filterMentionCandidates,
  MentionPopover,
} from "./MentionPopover";
import styles from "./ChatPane.module.css";

type MentionState = {
  // Position of `@` in textarea value, used as the start of the trigger token.
  start: number;
  // Substring after `@` up to caret. Used to filter the candidate list.
  query: string;
};

// `@` opens the popover only when it is at the very start of the input or
// preceded by whitespace/newline. This avoids hijacking emails, etc.
function detectMention(value: string, caret: number): MentionState | null {
  // Walk back from the caret looking for `@` or a token-terminator.
  for (let i = caret - 1; i >= 0; i--) {
    const ch = value[i];
    if (ch === "@") {
      const before = i === 0 ? "" : value[i - 1];
      if (i === 0 || /\s/.test(before)) {
        return { start: i, query: value.slice(i + 1, caret) };
      }
      return null;
    }
    // Stop scanning at any non-mention character; once we hit whitespace
    // or another `@`, we're outside the trigger token.
    if (/\s/.test(ch)) return null;
  }
  return null;
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
const SEND_HINT = isMac ? "⌘↵ to send" : "Ctrl↵ to send";

type ToolChipState =
  | { phase: "running"; brief: string }
  | { phase: "ok"; brief: string; promptId: number }
  | { phase: "fail"; brief: string; error: string };

export function ChatPane({ session }: { session: Session }) {
  const messages = useMessages(session.id);
  const invalidate = useChatInvalidation();
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [optimistic, setOptimistic] = useState<ChatMessage | null>(null);
  const [streaming, setStreaming] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [toolChip, setToolChip] = useState<ToolChipState | null>(null);
  const [mention, setMention] = useState<MentionState | null>(null);
  const [highlightedIdx, setHighlightedIdx] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const sourceImages = session.source_images;
  const mentionCandidates = useMemo(
    () =>
      mention
        ? filterMentionCandidates(sourceImages, mention.query)
        : [],
    [sourceImages, mention],
  );

  const rows = messages.data ?? [];
  const hasAnySources = session.source_images.length > 0;
  const showOptimistic = optimistic && !rows.some((r) => r.id === optimistic.id);
  const showStreamingThinking = pending && streaming.length === 0 && !toolChip;
  const showStreamingBubble = pending && streaming.length > 0;
  const totalCount = rows.length + (showOptimistic ? 1 : 0);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [rows.length, streaming, optimistic?.id, showStreamingThinking, toolChip]);

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
    setToolChip(null);
    setPending(true);
    try {
      await streamChat(session.id, content, {
        onDelta: (chunk) => setStreaming((s) => s + chunk),
        onDone: () => {
          invalidate.messages(session.id);
        },
        onError: (detail) => setError(detail),
        onToolCall: (_name, brief) => {
          setToolChip({ phase: "running", brief });
        },
        onToolResult: (result) => {
          if (result.ok) {
            setToolChip((cur) =>
              cur ? { phase: "ok", brief: cur.brief, promptId: result.promptId } : cur,
            );
            void qc.invalidateQueries({ queryKey: ["prompts", session.id] });
          } else {
            setToolChip((cur) =>
              cur ? { phase: "fail", brief: cur.brief, error: result.error } : cur,
            );
          }
        },
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setPending(false);
      setStreaming("");
      setOptimistic(null);
      // Tool chip stays visible after the turn ends — it is part of the
      // history of this in-session interaction. Cleared on the next send.
    }
  }

  function updateMention(value: string, caret: number) {
    const next = detectMention(value, caret);
    setMention(next);
    if (next === null) {
      setHighlightedIdx(0);
    }
  }

  function onChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    setDraft(value);
    updateMention(value, e.target.selectionStart ?? value.length);
  }

  function onSelectionChange(e: React.SyntheticEvent<HTMLTextAreaElement>) {
    const el = e.currentTarget;
    updateMention(el.value, el.selectionStart ?? el.value.length);
  }

  function insertMention(image: SourceImage) {
    if (!mention) return;
    const display = imageDisplayName(image);
    const before = draft.slice(0, mention.start);
    const after = draft.slice(mention.start + 1 + mention.query.length);
    const insertion = `@${display} `;
    const next = before + insertion + after;
    const caret = before.length + insertion.length;
    setDraft(next);
    setMention(null);
    setHighlightedIdx(0);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (mention !== null && mentionCandidates.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightedIdx((i) => (i + 1) % mentionCandidates.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightedIdx((i) =>
          (i - 1 + mentionCandidates.length) % mentionCandidates.length,
        );
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        insertMention(mentionCandidates[highlightedIdx]!);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(null);
        setHighlightedIdx(0);
        return;
      }
    }
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
              {hasAnySources
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
          {toolChip && <ToolChip state={toolChip} />}
          {showStreamingThinking && <ThinkingBubble />}
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        <div className={styles.composer}>
          <div className={styles.composerInputWrap}>
            <textarea
              ref={textareaRef}
              className={styles.textarea}
              placeholder={
                hasAnySources
                  ? "Describe the change…"
                  : "Add source image first"
              }
              value={draft}
              onChange={onChange}
              onKeyDown={onKeyDown}
              onSelect={onSelectionChange}
              onClick={onSelectionChange}
              onBlur={() => {
                // Defer so click events on popover items can run first.
                setTimeout(() => setMention(null), 100);
              }}
              disabled={pending}
            />
            <MentionPopover
              open={mention !== null && hasAnySources}
              query={mention?.query ?? ""}
              images={sourceImages}
              highlightedIndex={highlightedIdx}
              onHighlightChange={setHighlightedIdx}
              onSelect={insertMention}
            />
          </div>
          <div className={styles.composerRow}>
            <span className={styles.hint}>{SEND_HINT}</span>
            <div className={styles.spacer} />
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
          {role === "assistant" ? (
            <div className={styles.markdown}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </div>
          ) : (
            content
          )}
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

function ToolChip({ state }: { state: ToolChipState }) {
  if (state.phase === "running") {
    return (
      <div
        className={`${styles.toolChip} ${styles.toolChipRunning}`}
        role="status"
        aria-live="polite"
      >
        <Icon name="Sparkles" size={12} />
        <span>Regenerating prompt…</span>
        <span className={styles.toolChipBrief} title={state.brief}>
          {state.brief}
        </span>
      </div>
    );
  }
  if (state.phase === "ok") {
    return (
      <div className={`${styles.toolChip} ${styles.toolChipOk}`} role="status">
        <Icon name="Check" size={12} />
        <span>Prompt regenerated</span>
        <span className={styles.toolChipBrief} title={state.brief}>
          {state.brief}
        </span>
      </div>
    );
  }
  return (
    <div
      className={`${styles.toolChip} ${styles.toolChipFail}`}
      role="alert"
    >
      <Icon name="X" size={12} />
      <span>Generation failed: {state.error}</span>
    </div>
  );
}
