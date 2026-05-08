/** One card in the gallery — a job snapshot. Click → opens the
 *  SnapshotViewer modal. See docs/comfy-agents-ui-mock-plan.md. */
import type { JobSnapshot } from "../mocks/job-snapshots";
import styles from "./GalleryCard.module.css";

export function GalleryCard({
  job,
  onOpen,
  onDelete,
}: {
  job: JobSnapshot;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={styles.card}>
      <button
        type="button"
        className={styles.thumb}
        onClick={onOpen}
        title="Open snapshot"
      >
        {job.resultDataUrl ? (
          <img src={job.resultDataUrl} alt={job.workflowName} />
        ) : (
          <div className={styles.placeholder}>no result</div>
        )}
      </button>
      <div className={styles.meta}>
        <div className={styles.metaRow}>
          <span className={styles.name}>{job.workflowName}</span>
          <span className={styles.time}>{formatTime(job.createdAt)}</span>
        </div>
        <div className={styles.metaRow}>
          <span className={styles.dim}>
            {Object.keys(job.boundValues).length} slots
            {" · "}
            {job.agents.length} agents
          </span>
        </div>
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
  return (
    <div className={`${styles.card} ${styles.running}`}>
      <div className={styles.thumb}>
        <div className={styles.spinner}>●●●</div>
      </div>
      <div className={styles.meta}>
        <div className={styles.metaRow}>
          <span className={styles.name}>Generating…</span>
        </div>
        <div className={styles.dim}>queued · running · result fetch</div>
      </div>
    </div>
  );
}

function formatTime(epochMs: number): string {
  const d = new Date(epochMs);
  return d.toLocaleString();
}
