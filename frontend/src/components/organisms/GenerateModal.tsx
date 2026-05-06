import * as Dialog from "@radix-ui/react-dialog";
import MDEditor from "@uiw/react-md-editor";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  useGeneratePrompt,
  useSummarizeChat,
  type SummarizeContext,
} from "@/api/prompts";
import type { Session } from "@/api/sessions";
import { useIsReindexing } from "@/api/tasks";
import { ActionSettingsButton } from "@/components/molecules/ActionSettingsButton";
import styles from "./GenerateModal.module.css";

type Phase = "summarizing" | "reviewing" | "generating";

export function GenerateModal({
  session,
  open,
  onOpenChange,
}: {
  session: Session;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const summarize = useSummarizeChat(session.id);
  const generate = useGeneratePrompt(session.id);
  const isReindexing = useIsReindexing();

  const [brief, setBrief] = useState("");
  const [context, setContext] = useState<SummarizeContext | null>(null);
  const [compactHistory, setCompactHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phase: Phase = generate.isPending
    ? "generating"
    : summarize.isPending
      ? "summarizing"
      : "reviewing";

  // Kick off summarization every time the modal opens.
  useEffect(() => {
    if (!open) return;
    setBrief("");
    setContext(null);
    setCompactHistory(false);
    setError(null);
    summarize.mutate(undefined, {
      onSuccess: (data) => {
        setBrief(data.brief);
        setContext(data.context);
      },
      onError: (err) => setError(String(err)),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const blockReason = useMemo(() => {
    if (isReindexing) return "LoRA index is updating — try again in a moment.";
    return null;
  }, [isReindexing]);

  function handleClose(next: boolean) {
    // Block closing while a generation is in-flight; the orchestrator
    // call cannot be cancelled mid-flight anyway.
    if (phase === "generating") return;
    onOpenChange(next);
  }

  function handleGenerate() {
    setError(null);
    generate.mutate(
      { brief: brief.trim(), compactHistory },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => setError(String(err)),
      },
    );
  }

  function handleRetrySummarize() {
    setError(null);
    summarize.mutate(undefined, {
      onSuccess: (data) => {
        setBrief(data.brief);
        setContext(data.context);
      },
      onError: (err) => setError(String(err)),
    });
  }

  const summarizeError = !context && !!summarize.error;

  return (
    <Dialog.Root open={open} onOpenChange={handleClose}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.panel}
          aria-describedby={undefined}
          data-color-mode="light"
        >
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>
              Generate prompt
            </Dialog.Title>
            <div style={{ flex: 1 }} />
            <ActionSettingsButton
              action="summarize"
              session={session}
              disabled={phase !== "reviewing"}
              title="Summarize sampling settings"
            />
            <ActionSettingsButton
              action="generate"
              session={session}
              disabled={phase !== "reviewing"}
              title="Generate sampling settings"
            />
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.closeBtn}
                aria-label="Close"
                disabled={phase === "generating"}
              >
                <Icon name="X" />
              </button>
            </Dialog.Close>
          </div>

          <div className={styles.body}>
            {phase === "summarizing" && (
              <div className={styles.loadingState}>
                <Icon name="Sparkles" size={14} />
                <span>Summarizing the chat into a brief…</span>
              </div>
            )}

            {summarizeError && (
              <div className={styles.error} role="alert">
                <span>Could not summarize: {String(summarize.error)}</span>
                <Button size="sm" onClick={handleRetrySummarize}>
                  Retry
                </Button>
              </div>
            )}

            {context && (
              <>
                <section className={styles.section}>
                  <div className={styles.sectionHeader}>
                    <span>Brief</span>
                    <span className={styles.sectionHint}>
                      Read-only summary of the chat. To refine, cancel
                      and continue the discussion in chat — re-opening
                      the modal will re-run summarization.
                    </span>
                  </div>
                  <div className={styles.editorWrap} data-color-mode="light">
                    <MDEditor
                      height={240}
                      value={brief}
                      preview="preview"
                      hideToolbar
                      visibleDragbar={false}
                    />
                  </div>
                </section>

                <ContextPreview context={context} />

                <label className={styles.compactRow}>
                  <input
                    type="checkbox"
                    checked={compactHistory}
                    onChange={(e) =>
                      setCompactHistory(e.currentTarget.checked)
                    }
                    disabled={phase === "generating"}
                  />
                  <span>
                    Compact chat history after generation — replaces all
                    chat messages with the brief above. Useful for keeping
                    context small for local models on subsequent turns.
                  </span>
                </label>
              </>
            )}

            {blockReason && (
              <div className={styles.warn} role="alert">{blockReason}</div>
            )}
            {error && (
              <div className={styles.error} role="alert">{error}</div>
            )}
          </div>

          <div className={styles.foot}>
            <Button
              type="button"
              onClick={() => handleClose(false)}
              disabled={phase === "generating"}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              icon={<Icon name="Sparkles" size={12} />}
              onClick={handleGenerate}
              disabled={
                phase !== "reviewing" ||
                !brief.trim() ||
                !!blockReason
              }
            >
              {phase === "generating" ? "Generating…" : "Generate"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ContextPreview({ context }: { context: SummarizeContext }) {
  const main = context.main_image;
  const refs = context.reference_images;
  const pinned = context.pinned_loras;
  const slots = context.comfy_slots;
  const isComfy = slots !== null && slots !== undefined;
  return (
    <section className={styles.contextSection}>
      <div className={styles.sectionHeader}>
        <span>Context preview</span>
        <span className={styles.sectionHint}>
          Read-only. Family prompt guides are not shown — they always
          come from the model.
        </span>
      </div>
      <dl className={styles.contextGrid}>
        <dt>Mode</dt>
        <dd>{context.mode}</dd>
        <dt>Model</dt>
        <dd>
          {context.model_name ?? "—"}
          {context.family_display_name && (
            <span className={styles.faint}>
              {" "}· {context.family_display_name}
            </span>
          )}
        </dd>
        {!isComfy && (
          <>
            <dt>Negative</dt>
            <dd>{context.use_negative ? "enabled" : "disabled"}</dd>
          </>
        )}
        <dt>Pinned LoRAs</dt>
        <dd>
          {pinned.length === 0 ? (
            <span className={styles.faint}>none</span>
          ) : (
            <ul className={styles.loraList}>
              {pinned.map((p) => (
                <li key={p.name}>
                  <code>{p.name}</code>
                  {p.weight !== null && (
                    <span className={styles.faint}>
                      {" @ "}
                      {p.weight.toFixed(2)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
      {isComfy && <ComfySlotsPreview slots={slots!} />}
      {main && (
        <div className={styles.imageBlock}>
          <div className={styles.imageHead}>
            <span className={styles.imageLabel}>{main.label}</span>
            <span className={styles.faint}>main</span>
          </div>
          <p className={styles.imageBody}>{main.analysis}</p>
        </div>
      )}
      {refs.map((r) => (
        <div className={styles.imageBlock} key={r.label}>
          <div className={styles.imageHead}>
            <span className={styles.imageLabel}>{r.label}</span>
            <span className={styles.faint}>reference</span>
          </div>
          <p className={styles.imageBody}>{r.analysis}</p>
        </div>
      ))}
      {!isComfy && !main && refs.length === 0 && (
        <div className={styles.faint}>No source-image analyses yet.</div>
      )}
      {context.model_description && (
        <div className={styles.modelDesc}>
          <div className={styles.sectionHint}>Model description</div>
          <p className={styles.imageBody}>{context.model_description}</p>
        </div>
      )}
    </section>
  );
}

function ComfySlotsPreview({
  slots,
}: {
  slots: NonNullable<SummarizeContext["comfy_slots"]>;
}) {
  if (slots.length === 0) {
    return (
      <div className={styles.faint}>
        No slots labelled yet — open the slot mapping screen for this
        comfy session and add at least one.
      </div>
    );
  }
  // Group by `group`, groupless first.
  const groups = new Map<string, typeof slots>();
  for (const s of slots) {
    const key = s.group ?? "";
    const arr = groups.get(key) ?? [];
    arr.push(s);
    groups.set(key, arr);
  }
  return (
    <div className={styles.modelDesc}>
      <div className={styles.sectionHint}>
        Workflow slots ({slots.length})
      </div>
      {[...groups.entries()].map(([groupName, groupSlots]) => (
        <div key={groupName || "(ungrouped)"}>
          {groupName && (
            <div className={styles.imageHead}>
              <span className={styles.imageLabel}>{groupName}</span>
            </div>
          )}
          <ul className={styles.loraList}>
            {groupSlots.map((s) => (
              <li key={`${groupName}/${s.label}`}>
                <code>{s.label}</code>
                <span className={styles.faint}>
                  {" — "}
                  {s.kind} · {s.binding}
                  {s.binding === "frozen" && s.frozen_value !== undefined && (
                    <> · = {JSON.stringify(s.frozen_value)}</>
                  )}
                </span>
                {s.description && (
                  <div className={styles.faint}>{s.description}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
