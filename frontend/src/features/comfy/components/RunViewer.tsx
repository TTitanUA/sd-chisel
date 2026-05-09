/** Inline pipeline view — rendered as a centre-body mode next to
 *  "Agent editor" / "Node tree". Three regions stacked top-to-bottom:
 *
 *  - **Header** — title (Single Run · job id · generation id when a
 *    run exists) + the action button. The action button cycles
 *    between Start (idle / finished) and Cancel (in flight); the
 *    tiny × on the right dismisses a finished trace.
 *  - **Pipeline strip** — one chip per stage with pending /
 *    running / succeeded / failed / warning / skipped state derived
 *    from the SSE event stream.
 *  - **Event log** — append-only, newest at the bottom; one line
 *    per server event with its stage / event / detail summary.
 *    Patch slot_patched events render the assigned value.
 *
 *  The viewer renders even when no run has fired — the strip shows
 *  every stage as pending and the body invites the user to press
 *  Start. After a run finishes the user can dismiss the trace OR
 *  press Start again to fire another run.
 */
import { useEffect, useMemo, useRef } from "react";
import { useComfy } from "../state/useComfy";
import type { ComfyRunEvent } from "@/api/comfy";
import styles from "./RunViewer.module.css";

const STAGES = [
  "validate",
  "snapshot",
  "agents",
  "unload_lm",
  "upload_inputs",
  "patch",
  "queue",
  "execute",
  "save",
  "unload_comfy",
  "cleanup",
] as const;

type StageStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "warning"
  | "skipped";

const STATUS_LABEL: Record<StageStatus, string> = {
  pending: "—",
  running: "running",
  succeeded: "ok",
  failed: "error",
  warning: "warn",
  skipped: "skip",
};

function deriveStageStatuses(events: ComfyRunEvent[]): Record<string, StageStatus> {
  const out: Record<string, StageStatus> = {};
  for (const e of events) {
    const stage = typeof e.stage === "string" ? e.stage : null;
    const event = typeof e.event === "string" ? e.event : null;
    if (!stage) continue;
    if (event === "succeeded") out[stage] = "succeeded";
    else if (event === "failed" || event === "cancelled") out[stage] = "failed";
    else if (event === "warning") {
      out[stage] = out[stage] === "failed" ? "failed" : "warning";
    } else if (event === "skipped") out[stage] = "skipped";
    else if (event === "started") {
      if (out[stage] !== "succeeded" && out[stage] !== "failed") {
        out[stage] = "running";
      }
    } else if (out[stage] === undefined) {
      out[stage] = "running";
    }
  }
  return out;
}

function truncate(s: string, max = 200): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

/** Render a one-line summary of an event for the log pane. The
 *  patch stage's `slot_patched` event gets a special form that puts
 *  the assigned value front and center. */
function eventSummary(e: ComfyRunEvent): string {
  if (e.stage === "patch" && e.event === "slot_patched") {
    const label = String(e.slot_label ?? "?");
    const node = String(e.node_id ?? "?");
    const input = String(e.input_name ?? "?");
    let valueRepr = "(empty)";
    if (e.value !== undefined && e.value !== null) {
      valueRepr =
        typeof e.value === "string"
          ? JSON.stringify(truncate(e.value, 240))
          : truncate(JSON.stringify(e.value), 240);
    }
    return `${label} → #${node}.${input} = ${valueRepr}`;
  }
  const parts: string[] = [];
  if (typeof e.event === "string") parts.push(e.event);
  for (const k of [
    "agent_id", "name", "model", "slot_label", "comfy_filename",
    "filename", "node_id", "prompt_id", "client_id", "url", "value", "max",
    "message", "kept", "unloaded", "patched_count",
  ]) {
    const v = e[k as keyof ComfyRunEvent];
    if (v === undefined || v === null) continue;
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      parts.push(`${k}=${v}`);
    }
  }
  if (Array.isArray(e.warnings) && e.warnings.length > 0) {
    parts.push(`(${e.warnings.length} warning)`);
  }
  return parts.join(" · ");
}

function formatTs(ms: number | undefined): string {
  if (typeof ms !== "number") return "";
  return new Date(ms).toLocaleTimeString();
}

export function RunViewer({
  onDismiss,
  startDisabledReason,
}: {
  onDismiss: () => void;
  startDisabledReason: string | null;
}) {
  const { runState, runWorkflow, cancelRun } = useComfy();
  const logRef = useRef<HTMLDivElement>(null);

  const stageStatuses = useMemo(
    () => deriveStageStatuses(runState?.events ?? []),
    [runState?.events],
  );

  // Auto-scroll the event log to the bottom on each new event.
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [runState?.events.length]);

  const inProgress = runState?.inProgress === true;
  const hasFinishedTrace = runState !== null && !inProgress;

  let actionLabel: string;
  let actionDisabled = false;
  let actionTitle: string | undefined;
  let onAction: () => void;
  let actionVariant: "primary" | "danger" = "primary";

  if (inProgress) {
    actionLabel = "Cancel";
    onAction = () => void cancelRun();
    actionTitle = "Cancel the in-flight run";
    actionVariant = "danger";
  } else {
    actionLabel = hasFinishedTrace ? "Run again" : "Start";
    onAction = () => void runWorkflow();
    actionDisabled = startDisabledReason !== null;
    actionTitle = startDisabledReason ?? "Fire the Single Run pipeline";
  }

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <div className={styles.title}>
          <span className={styles.titleText}>Single Run</span>
          {runState && (
            <>
              <code className={styles.jobId}>{runState.jobId.slice(0, 8)}</code>
              <span className={styles.gen}>{runState.generationId}</span>
            </>
          )}
          {inProgress && <span className={styles.runningPill}>running</span>}
        </div>
        <div className={styles.actions}>
          <button
            type="button"
            className={
              actionVariant === "danger" ? styles.cancel : styles.start
            }
            onClick={onAction}
            disabled={actionDisabled}
            title={actionTitle}
          >
            {actionLabel}
          </button>
          {hasFinishedTrace && (
            <button
              type="button"
              className={styles.dismiss}
              onClick={onDismiss}
              title="Clear this run trace"
            >
              ×
            </button>
          )}
        </div>
      </header>

      <section className={styles.strip}>
        {STAGES.map((stage) => {
          const status: StageStatus = stageStatuses[stage] ?? "pending";
          return (
            <div
              key={stage}
              className={`${styles.stage} ${styles[`stage_${status}`]}`}
              title={`${stage}: ${status}`}
            >
              <span className={styles.stageName}>{stage}</span>
              <span className={styles.stageStatus}>
                {STATUS_LABEL[status]}
              </span>
            </div>
          );
        })}
      </section>

      <section className={styles.body} ref={logRef}>
        {!runState && (
          <div className={styles.empty}>
            {startDisabledReason
              ? startDisabledReason
              : "Press Start to fire the pipeline."}
          </div>
        )}
        {runState && runState.events.length === 0 && (
          <div className={styles.empty}>Waiting for first event…</div>
        )}
        {runState?.events.map((e, idx) => {
          const stage = typeof e.stage === "string" ? e.stage : "?";
          const event = typeof e.event === "string" ? e.event : "";
          const tone =
            event === "failed" || event === "warning" || event === "cancelled"
              ? styles[`event_${event}`]
              : "";
          return (
            <div
              key={`${stage}-${idx}-${e.ts ?? idx}`}
              className={`${styles.event} ${tone}`}
            >
              <span className={styles.eventTs}>{formatTs(e.ts)}</span>
              <span className={styles.eventStage}>{stage}</span>
              <span className={styles.eventBody}>{eventSummary(e)}</span>
            </div>
          );
        })}
      </section>
    </div>
  );
}
