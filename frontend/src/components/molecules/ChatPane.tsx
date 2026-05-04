import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  chatApi,
  streamChat,
  useChatInvalidation,
  useMessages,
  type ChatMessage,
} from "@/api/chat";
import { imageDisplayName, type Session, type SourceImage } from "@/api/sessions";
import { ActionSettingsButton } from "./ActionSettingsButton";
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

export function ChatPane({ session }: { session: Session }) {
  const messages = useMessages(session.id);
  const invalidate = useChatInvalidation();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [optimistic, setOptimistic] = useState<ChatMessage | null>(null);
  const [streaming, setStreaming] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [mention, setMention] = useState<MentionState | null>(null);
  const [highlightedIdx, setHighlightedIdx] = useState(0);
  // When set, the next Send call goes to /chat with replace_message_id —
  // the backend swaps the target user row's content, drops everything
  // after it, then streams a fresh assistant reply. Keeping the edit in
  // the composer (rather than inline on the bubble) means the standard
  // composer Send/Cancel flow does the work, and we can never end up
  // with two consecutive user turns.
  const [editingTargetId, setEditingTargetId] = useState<number | null>(null);
  const [actionPending, setActionPending] = useState(false);
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
  // i2i requires a source image as the visual anchor; t2i does not — the
  // chat works from text alone, with any uploaded images acting as
  // optional references.
  const isT2I = session.session_type === "t2i";
  const chatReady = isT2I || hasAnySources;
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
    const replaceId = editingTargetId;
    const isEdit = replaceId !== null;
    // For new turns we show an optimistic user bubble; for edits the
    // bubble is already in `rows` (we just hide its actions and mark it).
    // The composer is cleared in both cases so a successful send doesn't
    // leave the edited text sitting in the composer.
    const tempUser: ChatMessage | null = isEdit ? null : {
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
    let failed = false;
    try {
      await streamChat(
        session.id,
        content,
        {
          onDelta: (chunk) => setStreaming((s) => s + chunk),
          onDone: () => {
            invalidate.messages(session.id);
          },
          onError: (detail) => {
            failed = true;
            setError(detail);
          },
        },
        replaceId !== null ? { replaceMessageId: replaceId } : undefined,
      );
    } catch (err) {
      failed = true;
      setError(String(err));
    } finally {
      setPending(false);
      setStreaming("");
      setOptimistic(null);
      if (failed) {
        // For new turns the backend rolls back the persisted user row,
        // so restoring the draft lets the user retry. For edits the
        // backend keeps the edit committed (truncate+replace already
        // happened) — refresh the list and clear the editing state so
        // the user can either re-edit or send a new turn.
        if (isEdit) {
          invalidate.messages(session.id);
          setEditingTargetId(null);
        } else {
          setDraft((d) => (d ? d : content));
        }
      } else if (isEdit) {
        setEditingTargetId(null);
      }
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

  async function handleDelete(id: number) {
    if (actionPending) return;
    if (!window.confirm("Delete this message?")) return;
    if (editingTargetId === id) cancelEdit();
    setActionPending(true);
    setError(null);
    try {
      await chatApi.deleteMessage(session.id, id);
      invalidate.messages(session.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setActionPending(false);
    }
  }

  function startEdit(m: ChatMessage) {
    if (pending || actionPending) return;
    setEditingTargetId(m.id);
    setDraft(m.content);
    setError(null);
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      // Place caret at the end so the user can extend or backspace.
      const end = el.value.length;
      el.setSelectionRange(end, end);
    });
  }

  function cancelEdit() {
    setEditingTargetId(null);
    setDraft("");
  }

  async function handleClear() {
    if (actionPending || pending) return;
    if (rows.length === 0) return;
    if (!window.confirm("Clear all chat messages? This cannot be undone.")) return;
    cancelEdit();
    setActionPending(true);
    setError(null);
    try {
      await chatApi.clearMessages(session.id);
      invalidate.messages(session.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setActionPending(false);
    }
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
    if (e.key === "Escape" && editingTargetId !== null) {
      e.preventDefault();
      cancelEdit();
      return;
    }
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  }

  // If the message being edited disappears from the list (deleted from
  // another tab, cleared, or wiped by a previous edit cascade), drop the
  // editing state so the composer doesn't keep targeting a missing row.
  useEffect(() => {
    if (editingTargetId === null) return;
    if (!rows.some((r) => r.id === editingTargetId)) {
      setEditingTargetId(null);
      setDraft("");
    }
  }, [editingTargetId, rows]);

  const editingTarget = editingTargetId !== null
    ? rows.find((r) => r.id === editingTargetId) ?? null
    : null;

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
        <Button
          size="sm"
          variant="ghost"
          icon={<Icon name="BrushCleaning" size={12} />}
          onClick={() => void handleClear()}
          disabled={pending || actionPending || rows.length === 0}
          title="Clear all chat messages"
        >
          Clear
        </Button>
      </div>
      <div className={styles.body}>
        <div className={styles.scroll} ref={scrollRef}>
          {rows.length === 0 && !showOptimistic && !showStreamingThinking && !showStreamingBubble && (
            <div className={styles.empty}>
              {chatReady ? (
                isT2I ? (
                  <>Describe the image you want to create. I&rsquo;ll pick LoRAs from your library and assemble a prompt.</>
                ) : (
                  <>Describe the change you want. I&rsquo;ll pick LoRAs from your library and assemble a prompt.</>
                )
              ) : (
                <>Add a source image first &mdash; I need a VL summary to anchor the prompt.</>
              )}
            </div>
          )}
          {rows.map((m) => (
            <Bubble
              key={m.id}
              role={m.role}
              content={m.content}
              createdAt={m.created_at}
              editable={m.role === "user"}
              isEditing={editingTargetId === m.id}
              onEditStart={() => startEdit(m)}
              onDelete={() => void handleDelete(m.id)}
              actionsDisabled={pending || actionPending}
            />
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
          {editingTarget && (
            <div className={styles.editBanner}>
              <Icon name="Pencil" size={12} />
              <span className={styles.editBannerText}>
                Editing your message — sending will replace it and drop
                everything below.
              </span>
              <button
                type="button"
                className={styles.editBannerClose}
                onClick={cancelEdit}
                disabled={pending}
                aria-label="Cancel edit"
                title="Cancel edit"
              >
                <Icon name="X" size={12} />
              </button>
            </div>
          )}
          <div className={styles.composerInputWrap}>
            <textarea
              ref={textareaRef}
              className={styles.textarea}
              placeholder={
                chatReady
                  ? isT2I
                    ? "Describe the image…"
                    : "Describe the change…"
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
            <ActionSettingsButton
              action="chat"
              session={session}
              disabled={pending}
              title="Chat sampling settings"
            />
            <Button
              size="sm"
              variant="primary"
              icon={<Icon name="Send" size={12} />}
              onClick={() => void send()}
              disabled={pending || draft.trim().length === 0}
            >
              {pending
                ? (editingTarget ? "Saving…" : "Sending…")
                : (editingTarget ? "Save & send" : "Send")}
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
  editable = false,
  isEditing = false,
  onEditStart,
  onDelete,
  actionsDisabled = false,
}: {
  role: "user" | "assistant" | "system";
  content: string;
  createdAt: number;
  streaming?: boolean;
  editable?: boolean;
  isEditing?: boolean;
  onEditStart?: () => void;
  onDelete?: () => void;
  actionsDisabled?: boolean;
}) {
  const time = useMemo(() => formatTime(createdAt), [createdAt]);
  const variantClass = role === "user" ? "ds-chat-user" : "ds-chat-assistant";
  const hostClass = [
    "ds-chat",
    variantClass,
    styles.bubbleHost,
    isEditing ? styles.bubbleEditing : null,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={hostClass}>
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
          {isEditing && <span className={styles.editingTag}> · editing</span>}
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
      {editable && (
        <div className={styles.bubbleActions}>
          <button
            type="button"
            className={styles.iconBtn}
            onClick={() => onEditStart?.()}
            disabled={actionsDisabled || isEditing}
            aria-label="Edit message"
            title="Edit (drops everything after this turn)"
          >
            <Icon name="Pencil" size={12} />
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            onClick={() => onDelete?.()}
            disabled={actionsDisabled}
            aria-label="Delete message"
            title="Delete message"
          >
            <Icon name="Trash2" size={12} />
          </button>
        </div>
      )}
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

