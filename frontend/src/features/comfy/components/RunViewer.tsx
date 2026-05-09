/** Inline pipeline view — rendered as a third centre-body mode next
 *  to "Agent editor" / "Node tree". Two regions stacked top-to-bottom:
 *
 *  - **Pipeline strip** (top) — one chip per stage with pending /
 *    running / succeeded / failed / warning / skipped state derived
 *    from the SSE event stream.
 *  - **Event log** (bottom) — append-only, newest at the bottom; one
 *    line per server event with its stage / event / detail summary.
 *
 *  When the run terminates the user can dismiss to clear runState
 *  (the centre body falls back to the previously-active mode); while
 *  inProgress, dismissal is refused and the dismiss button surfaces
 *  the reason. */
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

/** Reduce the event stream into a per-stage status. The orchestrator
 *  publishes ``event=started/succeeded/failed/warning/skipped/...``
 *  per stage; we keep the latest, with "running" inferred from the
 *  presence of any event lacking a terminal verdict. */
function deriveStageStatuses(events: ComfyRunEvent[]): Record<string, StageStatus> {
  const out: Record<string, StageStatus> = {};
  for (const e of events) {
    const stage = typeof e.stage === "string" ? e.stage : null;
    const event = typeof e.event === "string" ? e.event : null;
    if (!stage) continue;
    if (event === "succeeded") out[stage] = "succeeded";
    else if (event === "failed") out[stage] = "failed";
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

/** Render a one-line summary of an event for the log pane. */
function eventSummary(e: ComfyRunEvent): string {
  const parts: string[] = [];
  if (typeof e.event === "string") parts.push(e.event);
  for (const k of [
    "agent_id", "name", "model", "slot_label", "comfy_filename",
    "filename", "node_id", "prompt_id", "client_id", "url", "value", "max",
    "message", "kept", "unloaded",
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
  onClose,
}: {
  onClose: () => void;
}) {
  const { runState } = useComfy();
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

  if (!runState) return null;

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <div className={styles.title}>
          <span className={styles.titleText}>Single Run</span>
          <code className={styles.jobId}>{runState.jobId.slice(0, 8)}</code>
          <span className={styles.gen}>{runState.generationId}</span>
          {runState.inProgress && (
            <span className={styles.runningPill}>running</span>
          )}
        </div>
        <button
          type="button"
          className={styles.close}
          onClick={onClose}
          disabled={runState.inProgress}
          title={runState.inProgress
            ? "Run is in progress — wait for it to finish"
            : "Dismiss this run trace"}
        >
          {runState.inProgress ? "Running…" : "Dismiss"}
        </button>
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
        {runState.events.length === 0 && (
          <div className={styles.empty}>Waiting for first event…</div>
        )}
        {runState.events.map((e, idx) => {
          const stage = typeof e.stage === "string" ? e.stage : "?";
          const event = typeof e.event === "string" ? e.event : "";
          const tone =
            event === "failed" || event === "warning"
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
