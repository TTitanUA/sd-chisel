/** One card in the gallery — a real Single Run job (comfy_jobs row).
 *  Stripped to just the result thumbnail + a colour-coded border:
 *  click opens the SnapshotViewer modal that owns every action and
 *  every byte of metadata. The hover tooltip carries enough context
 *  (generation id, timestamp, status) to identify the card without
 *  opening it. */
import type { ComfyJob } from "@/api/comfy";
import { useComfy } from "../state/useComfy";
import styles from "./GalleryCard.module.css";

export function GalleryCard({
  job,
  onOpen,
}: {
  job: ComfyJob;
  onOpen: () => void;
}) {
  const primary = job.outputs.find((o) => o.is_primary) ?? job.outputs[0];
  const slotCount = Object.keys(job.payload).length;
  const tooltip =
    `${job.generation_id}\n` +
    `${formatTime(job.started_at)}\n` +
    `${job.status} · ${slotCount} slot(s) · ${job.agents_snapshot.length} agent(s)` +
    (job.error_message ? `\n${job.error_message}` : "");
  const stateClass =
    job.status === "error"
      ? styles.errored
      : job.status === "cancelled"
      ? styles.cancelled
      : "";
  return (
    <button
      type="button"
      className={`${styles.card} ${stateClass}`}
      onClick={onOpen}
      title={tooltip}
    >
      {primary ? (
        <img
          className={styles.thumbImg}
          src={primary.url}
          alt={primary.slot_label ?? "result"}
        />
      ) : (
        <div className={styles.placeholder}>
          {job.status === "error" ? "error" : "no result"}
        </div>
      )}
    </button>
  );
}

export function RunningJobCard() {
  const { runState } = useComfy();
  const stage = runState?.currentStage ?? "validate";
  return (
    <div
      className={`${styles.card} ${styles.running}`}
      title={`Running — stage: ${stage}`}
    >
      <div className={styles.spinner}>●●●</div>
    </div>
  );
}

/** Epoch seconds → locale string. The repo stores started_at as a
 *  unix timestamp in seconds; multiply for the JS Date constructor. */
function formatTime(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return d.toLocaleString();
}
