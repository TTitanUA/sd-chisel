import { useEffect, useRef, useState } from "react";
import type { Task } from "@/api/tasks";
import { useActiveTasks } from "@/api/tasks";
import styles from "./TaskListPopover.module.css";

export function TaskListPopover() {
  const tasks = useActiveTasks();
  const list = tasks.data ?? [];
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (list.length === 0) return null;

  return (
    <div className={styles.wrap} ref={ref}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        aria-label={`${list.length} background task${list.length === 1 ? "" : "s"} running`}
        aria-expanded={open}
      >
        <span className={styles.spinner} aria-hidden="true" />
        <span className={styles.count}>{list.length}</span>
      </button>
      {open && (
        <div className={styles.popover} role="dialog" aria-label="Background tasks">
          {list.length === 0 ? (
            <div className={styles.empty}>No active tasks.</div>
          ) : (
            list.map((task) => <TaskRow key={task.id} task={task} />)
          )}
        </div>
      )}
    </div>
  );
}

function TaskRow({ task }: { task: Task }) {
  return (
    <div className={styles.task}>
      <div className={styles.taskHeader}>
        <span className={styles.taskTitle} title={task.title}>
          {task.title}
        </span>
        <span
          className={`${styles.statusBadge} ${
            task.status === "running"
              ? styles.statusRunning
              : task.status === "failed"
                ? styles.statusFailed
                : ""
          }`}
        >
          {task.status}
        </span>
      </div>
      {task.message && <div className={styles.message}>{task.message}</div>}
      <div className={styles.progressBar}>
        <div
          className={`${styles.progressFill} ${
            task.progress == null ? styles.progressIndeterminate : ""
          }`}
          style={
            task.progress != null
              ? { width: `${Math.round(task.progress * 100)}%` }
              : undefined
          }
        />
      </div>
    </div>
  );
}
