/** One card in the gallery — a real Single Run job (comfy_jobs row).
 *  Click → opens the SnapshotViewer modal with the run's frozen
 *  payload + agents snapshot + outputs. */
import type { ComfyJob } from "@/api/comfy";
import { useComfy } from "../state/useComfy";
import styles from "./GalleryCard.module.css";

export function GalleryCard({
  job,
  onOpen,
  onDelete,
}: {
  job: ComfyJob;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const primary = job.outputs.find((o) => o.is_primary) ?? job.outputs[0];
  const slotCount = Object.keys(job.payload).length;
  return (
    <div className={`${styles.card} ${job.status === "error" ? styles.errored : ""}`}>
      <button
        type="button"
        className={styles.thumb}
        onClick={onOpen}
        title="Open snapshot"
      >
        {primary ? (
          <img src={primary.url} alt={primary.slot_label ?? "result"} />
        ) : (
          <div className={styles.placeholder}>
            {job.status === "error" ? "error" : "no result"}
          </div>
        )}
      </button>
      <div className={styles.meta}>
        <div className={styles.metaRow}>
          <span className={styles.name}>{job.generation_id}</span>
          <span className={styles.time}>{formatTime(job.started_at)}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.dim}>
            {job.status} · {slotCount} slots · {job.agents_snapshot.length} agents
          </span>
        </div>
        {job.error_message && (
          <div className={styles.errorMsg}>{job.error_message}</div>
        )}
        <div className={styles.actions}>
          <button type="button" onClick={onOpen}>
            Open snapshot
          </button>
          <button type="button" onClick={onDelete} className={styles.delete}>
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export function RunningJobCard() {
  const { runState } = useComfy();
  const stage = runState?.currentStage ?? "validate";
  return (
    <div className={`${styles.card} ${styles.running}`}>
      <div className={styles.thumb}>
        <div className={styles.spinner}>●●●</div>
      </div>
      <div className={styles.meta}>
        <div className={styles.metaRow}>
          <span className={styles.name}>Running…</span>
        </div>
        <div className={styles.dim}>stage: {stage}</div>
      </div>
    </div>
  );
}

/** Epoch seconds → locale string. The repo stores started_at as a
 *  unix timestamp in seconds; multiply for the JS Date constructor. */
function formatTime(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleString();
}
