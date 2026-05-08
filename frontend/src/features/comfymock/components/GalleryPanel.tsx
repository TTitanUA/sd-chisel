/** Gallery — a grid of past job snapshots, newest first. While a
 *  workflow is generating, a RunningJobCard pins to the top. Click a
 *  card → SnapshotViewer modal. See docs/comfy-agents-ui-mock-plan.md. */
import { useState } from "react";
import { useComfyMock } from "../state/useComfyMock";
import { GalleryCard, RunningJobCard } from "./GalleryCard";
import { SnapshotViewer } from "./SnapshotViewer";
import styles from "./GalleryPanel.module.css";

export function GalleryPanel() {
  const { jobs, isRunningWorkflow, deleteJob } = useComfyMock();
  const [openJobId, setOpenJobId] = useState<string | null>(null);

  const openJob = jobs.find((j) => j.id === openJobId) ?? null;

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>
          Gallery ({jobs.length})
        </span>
      </div>
      <div className={styles.body}>
        {isRunningWorkflow && <RunningJobCard />}
        {jobs.length === 0 && !isRunningWorkflow && (
          <div className={styles.empty}>
            No runs yet. Press <strong>Generate workflow</strong> in the
            header once every binding=llm slot is filled.
          </div>
        )}
        {jobs.map((job) => (
          <GalleryCard
            key={job.id}
            job={job}
            onOpen={() => setOpenJobId(job.id)}
            onDelete={() => deleteJob(job.id)}
          />
        ))}
      </div>
      {openJob && (
        <SnapshotViewer job={openJob} onClose={() => setOpenJobId(null)} />
      )}
    </div>
  );
}
