/** Modal that explodes a comfy_jobs row into a 3-panel inspection view:
 *  state (every agent's prompt + last_value), bindings (workflow slot
 *  → resolved value), result (primary output full-size).
 *
 *  The gallery card surface is image-only; every action lives here:
 *  Delete (drops the row + files server-side), Close (×). Tab strip
 *  between Result / Bindings / State for inspection. */
import { useState } from "react";
import type { ComfyJob } from "@/api/comfy";
import styles from "./SnapshotViewer.module.css";

type Tab = "state" | "bindings" | "result";

export function SnapshotViewer({
  job,
  onClose,
  onDelete,
}: {
  job: ComfyJob;
  onClose: () => void;
  onDelete: () => void;
}) {
  const [tab, setTab] = useState<Tab>("result");
  const primary = job.outputs.find((o) => o.is_primary) ?? job.outputs[0];

  function handleDelete() {
    if (!confirm(`Delete run ${job.generation_id}? This drops files too.`)) {
      return;
    }
    onDelete();
    onClose();
  }

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <header className={styles.header}>
          <div>
            <div className={styles.title}>{job.generation_id}</div>
            <div className={styles.subtitle}>
              {new Date(job.started_at * 1000).toLocaleString()} · job{" "}
              <code>{job.id.slice(0, 8)}</code> · {job.status}
            </div>
          </div>
          <div className={styles.tabs}>
            <button
              className={tab === "state" ? styles.active : ""}
              onClick={() => setTab("state")}
            >
              State
            </button>
            <button
              className={tab === "bindings" ? styles.active : ""}
              onClick={() => setTab("bindings")}
            >
              Bindings
            </button>
            <button
              className={tab === "result" ? styles.active : ""}
              onClick={() => setTab("result")}
            >
              Result
            </button>
          </div>
          <button
            type="button"
            className={styles.delete}
            onClick={handleDelete}
            title="Delete this run + its output files"
          >
            Delete
          </button>
          <button className={styles.close} onClick={onClose} title="Close">
            ×
          </button>
        </header>

        <div className={styles.body}>
          {tab === "result" && (
            <div className={styles.resultWrap}>
              {primary ? (
                <img
                  src={primary.url}
                  alt={primary.slot_label ?? "result"}
                  className={styles.resultImage}
                />
              ) : (
                <div className={styles.empty}>
                  {job.error_message
                    ? `Run failed: ${job.error_message}`
                    : "No result image stored."}
                </div>
              )}
            </div>
          )}

          {tab === "bindings" && (
            <div className={styles.list}>
              {Object.entries(job.payload).map(([label, value]) => (
                <div key={label} className={styles.bindingRow}>
                  <div className={styles.bindingLabel}>{label}</div>
                  <pre className={styles.bindingValue}>{stringify(value)}</pre>
                </div>
              ))}
            </div>
          )}

          {tab === "state" && (
            <div className={styles.list}>
              {job.agents_snapshot.map((a) => (
                <div key={a.id} className={styles.agent}>
                  <div className={styles.agentName}>{a.name}</div>
                  <div className={styles.agentMeta}>
                    model={a.model_name ?? "default"} · sources=
                    {a.source_scope} · LoRAs={a.loras_enabled ? "on" : "off"}
                  </div>
                  {a.prompt && (
                    <div className={styles.agentPrompt}>{a.prompt}</div>
                  )}
                  <div className={styles.list}>
                    {a.output_slots.map((s) => (
                      <div key={s.id} className={styles.slot}>
                        <div className={styles.slotLabel}>
                          {s.label}
                          {s.bound_to && (
                            <em>
                              {" "}
                              ↳ {s.bound_to.workflow_slot_label}
                            </em>
                          )}
                        </div>
                        <pre className={styles.slotValue}>
                          {stringify(s.last_value)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function stringify(v: unknown): string {
  if (v === null || v === undefined) return "(empty)";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}
