/** Gallery — a grid of past job snapshots, newest first. While a
 *  workflow is generating, a RunningJobCard pins to the top. Click a
 *  card → SnapshotViewer modal. */
import { useState } from "react";
import { useComfy } from "../state/useComfy";
import { GalleryCard, RunningJobCard } from "./GalleryCard";
import { SnapshotViewer } from "./SnapshotViewer";
import styles from "./GalleryPanel.module.css";

export function GalleryPanel() {
  const { jobs, runState, isRunningWorkflow, deleteJob } = useComfy();
  const [openJobId, setOpenJobId] = useState<string | null>(null);

  // The active run's comfy_jobs row exists in the DB the moment the
  // SNAPSHOT stage commits — well before SAVE writes outputs. Rendering
  // it as a regular GalleryCard would show a "no result" placeholder
  // alongside the synthetic <RunningJobCard /> below. Hide that DB row
  // while the run is live; the synthetic card carries the live stage
  // info from the SSE stream.
  const liveJobId = runState?.jobId ?? null;
  const visibleJobs = liveJobId
    ? jobs.filter((j) => j.id !== liveJobId)
    : jobs;

  const openJob = jobs.find((j) => j.id === openJobId) ?? null;

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>
          Gallery ({visibleJobs.length + (isRunningWorkflow ? 1 : 0)})
        </span>
      </div>
      <div className={styles.body}>
        {isRunningWorkflow && <RunningJobCard />}
        {visibleJobs.length === 0 && !isRunningWorkflow && (
          <div className={styles.empty}>
            No runs yet. Open the <strong>Single Run</strong> tab and
            press Start once every binding=llm slot is filled.
          </div>
        )}
        {visibleJobs.map((job) => (
          <GalleryCard
            key={job.id}
            job={job}
            onOpen={() => setOpenJobId(job.id)}
          />
        ))}
      </div>
      {openJob && (
        <SnapshotViewer
          job={openJob}
          onClose={() => setOpenJobId(null)}
          onDelete={() => deleteJob(openJob.id)}
        />
      )}
    </div>
  );
}
