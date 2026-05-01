import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import type { AssistStreamFn } from "@/api/assist";
import { useLmModels } from "@/api/settings";
import styles from "./AssistantPane.module.css";

export type ImportSource = {
  id: string;
  label: string;
  iconUrl?: string;
  inputLabel: string;
  inputPlaceholder: string;
  inputHint?: string;
  fetchAndFormat: (ref: string) => Promise<string>;
};

type ChatEntry = { role: "user" | "assistant"; content: string };

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
const SEND_HINT = isMac ? "⌘↵ to send" : "Ctrl↵ to send";

function normalizeAssistantText(raw: string): string {
  return raw.replace(/\n{3,}/g, "\n\n").trim();
}

export function AssistantPane<S>({
  getCurrentState,
  onArtifact,
  streamFn,
  toolLabels = {},
  placeholder = "Describe or paste docs…",
  emptyMessage = "Paste documentation or describe the item to get started.",
  importSources = [],
}: {
  getCurrentState: () => S;
  onArtifact: (field: string, content: string) => void;
  streamFn: AssistStreamFn<S>;
  toolLabels?: Record<string, string>;
  placeholder?: string;
  emptyMessage?: string;
  importSources?: ImportSource[];
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

  const [showSources, setShowSources] = useState(false);
  const [activeSource, setActiveSource] = useState<ImportSource | null>(null);
  const [importRef, setImportRef] = useState("");
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const dropupRef = useRef<HTMLDivElement>(null);
  const dialogInputRef = useRef<HTMLInputElement>(null);

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

  // Close dropup when clicking outside
  useEffect(() => {
    if (!showSources) return;
    function onDocClick(e: MouseEvent) {
      if (dropupRef.current && !dropupRef.current.contains(e.target as Node)) {
        setShowSources(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [showSources]);

  // Auto-focus dialog input + handle Esc
  useEffect(() => {
    if (!activeSource) return;
    dialogInputRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !importLoading) closeDialog();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [activeSource, importLoading]);

  const send = useCallback(
    async (overrideContent?: string) => {
      const content = (overrideContent ?? draft).trim();
      if (!content || pending || !model) return;

      setMessages((prev) => [...prev, { role: "user", content }]);
      if (overrideContent === undefined) setDraft("");
      setStreaming("");
      setCurrentTool(null);
      setToolCount(0);
      setError(null);
      setPending(true);

      const snapshot = getCurrentState();
      let assistantText = "";
      try {
        await streamFn(model, content, responseId, snapshot, {
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
    },
    [draft, pending, model, responseId, streamFn, getCurrentState, onArtifact],
  );

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  }

  function openSource(src: ImportSource) {
    setShowSources(false);
    setActiveSource(src);
    setImportRef("");
    setImportError(null);
  }

  function closeDialog() {
    setActiveSource(null);
    setImportRef("");
    setImportError(null);
  }

  async function submitImport() {
    if (!activeSource || importLoading) return;
    const ref = importRef.trim();
    if (!ref) return;
    if (!model) {
      setImportError("Pick an assistant model first.");
      return;
    }
    setImportLoading(true);
    setImportError(null);
    try {
      const message = await activeSource.fetchAndFormat(ref);
      setActiveSource(null);
      setImportRef("");
      void send(message);
    } catch (err) {
      setImportError(String(err instanceof Error ? err.message : err));
    } finally {
      setImportLoading(false);
    }
  }

  const streamingDisplay = pending ? normalizeAssistantText(streaming) : "";
  const showThinking = pending && streamingDisplay.length === 0 && !currentTool;
  const showStreaming = pending && streamingDisplay.length > 0;
  const toolLabel = currentTool
    ? (toolLabels[currentTool] ?? `running ${currentTool}…`)
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
              {emptyMessage}
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
          {importSources.length > 0 && (
            <div className={styles.toolbar} ref={dropupRef}>
              <button
                type="button"
                className={styles.toolButton}
                onClick={() => setShowSources((v) => !v)}
                disabled={pending || importLoading}
                aria-haspopup="menu"
                aria-expanded={showSources}
              >
                <Icon name="Plus" size={11} />
                <span>Import</span>
              </button>
              {showSources && (
                <div className={styles.dropup} role="menu">
                  {importSources.map((src) => (
                    <button
                      key={src.id}
                      type="button"
                      role="menuitem"
                      className={styles.dropupItem}
                      onClick={() => openSource(src)}
                    >
                      {src.iconUrl && (
                        <img
                          src={src.iconUrl}
                          alt=""
                          className={styles.dropupIcon}
                        />
                      )}
                      <span>{src.label}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <textarea
            className={styles.textarea}
            placeholder={placeholder}
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

      {activeSource && (
        <div
          className={styles.dialogBackdrop}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !importLoading) closeDialog();
          }}
        >
          <div className={styles.dialog} role="dialog" aria-modal="true">
            <h3 className={styles.dialogTitle}>
              {activeSource.iconUrl && (
                <img
                  src={activeSource.iconUrl}
                  alt=""
                  className={styles.dialogTitleIcon}
                />
              )}
              <span>Import from {activeSource.label}</span>
            </h3>
            <label className={styles.dialogFieldLabel}>
              {activeSource.inputLabel}
            </label>
            <input
              ref={dialogInputRef}
              className={styles.dialogInput}
              value={importRef}
              onChange={(e) => setImportRef(e.currentTarget.value)}
              placeholder={activeSource.inputPlaceholder}
              disabled={importLoading}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void submitImport();
                }
              }}
            />
            {activeSource.inputHint && (
              <div className={styles.dialogHint}>{activeSource.inputHint}</div>
            )}
            {importError && (
              <div className={styles.dialogError} role="alert">{importError}</div>
            )}
            <div className={styles.dialogActions}>
              <Button
                type="button"
                variant="ghost"
                onClick={closeDialog}
                disabled={importLoading}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={() => void submitImport()}
                disabled={importLoading || importRef.trim() === ""}
              >
                {importLoading ? "Fetching…" : "Import"}
              </Button>
            </div>
          </div>
        </div>
      )}
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
