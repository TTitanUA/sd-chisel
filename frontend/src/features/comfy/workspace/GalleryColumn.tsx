import { Icon } from "@/components/atoms/Icon";
import styles from "./GalleryColumn.module.css";

/** Centre column — gallery of past comfy_jobs grouped by run.
 *
 * Mock PR is an empty state. Live PR (Phase 3) will:
 *   - pin a running-job progress card to the top while in flight,
 *   - render per-job result groups newest first with collapsible
 *     bindings/overrides snapshots,
 *   - support per-card actions (regenerate, show payload, delete). */
export function GalleryColumn() {
  return (
    <div className={styles.column} aria-label="Gallery">
      <div className={styles.head}>
        <span className={styles.title}>Gallery</span>
        <span className={styles.sub}>0 jobs</span>
      </div>
      <div className={styles.empty}>
        <Icon name="Sparkles" size={28} />
        <h3 className={styles.emptyTitle}>No generations yet</h3>
        <p className={styles.emptyBody}>
          Press <strong>Generate</strong> in the header to compose a brief and
          queue the workflow. Past jobs and the running-job progress card will
          appear here, newest first.
        </p>
      </div>
    </div>
  );
}
