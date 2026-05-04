import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { runImport, type ImportEvent, type ReadinessCard } from "@/api/comfy";
import styles from "./ComfyBulkImportModal.module.css";

type RowState = "pending" | "running" | "succeeded" | "failed";

type Row = {
  classType: string;
  displayName: string;
  state: RowState;
  detail?: string;
};

/** Bulk-import every `needs_config` node from the readiness panel.
 *
 * Reuses the per-node SSE wizard (`runImport`) — for each target it
 * subscribes to the stream, waits for `done` or `stage_failed`, then
 * moves on. A failure on one node skips that node and continues with
 * the rest, so the operator can leave the modal alone and come back to
 * a finished list. */
export function ComfyBulkImportModal({
  targets,
  open,
  onOpenChange,
  onCompleted,
}: {
  targets: ReadinessCard[];
  open: boolean;
  onOpenChange: (value: boolean) => void;
  onCompleted?: () => void;
}) {
  const client = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const cancelledRef = useRef(false);

  const [rows, setRows] = useState<Row[]>([]);
  const [cursor, setCursor] = useState(0);
  const [running, setRunning] = useState(false);

  // Reset and start whenever the modal opens with a fresh target list.
  useEffect(() => {
    if (!open) {
      abortRef.current?.abort();
      cancelledRef.current = true;
      return;
    }
    cancelledRef.current = false;
    setRows(
      targets.map((t) => ({
        classType: t.class_type,
        displayName: t.display_name ?? t.class_type,
        state: "pending",
      })),
    );
    setCursor(0);
    setRunning(true);
    void runAll(targets);
    return () => {
      abortRef.current?.abort();
      cancelledRef.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function runAll(items: ReadinessCard[]) {
    for (let i = 0; i < items.length; i++) {
      if (cancelledRef.current) break;
      setCursor(i);
      const target = items[i];
      const abort = new AbortController();
      abortRef.current = abort;

      setRows((prev) =>
        prev.map((r, idx) =>
          idx === i ? { ...r, state: "running", detail: undefined } : r,
        ),
      );

      let lastError: string | undefined;
      let succeeded = false;

      const handle = (event: ImportEvent) => {
        switch (event.type) {
          case "stage_failed":
            if (event.stage !== "internal") {
              lastError = `${event.stage}: ${event.error}`;
            } else if (!lastError) {
              lastError = event.error;
            }
            break;
          case "done":
            succeeded = true;
            break;
        }
      };

      try {
        await runImport(target.class_type, handle, abort.signal);
      } catch (exc) {
        if (!cancelledRef.current) {
          lastError = (exc as Error).message;
        }
      }

      if (cancelledRef.current) break;

      setRows((prev) =>
        prev.map((r, idx) =>
          idx === i
            ? {
                ...r,
                state: succeeded ? "succeeded" : "failed",
                detail: succeeded ? "imported" : lastError ?? "skipped",
              }
            : r,
        ),
      );
    }

    if (!cancelledRef.current) {
      setRunning(false);
      // Refresh catalog + readiness so cards flip to ready as a batch.
      void client.invalidateQueries({ queryKey: ["comfy"] });
      onCompleted?.();
    }
  }

  function cancel() {
    cancelledRef.current = true;
    abortRef.current?.abort();
    setRunning(false);
  }

  const total = rows.length;
  const done = rows.filter((r) => r.state === "succeeded" || r.state === "failed").length;
  const succeeded = rows.filter((r) => r.state === "succeeded").length;
  const failed = rows.filter((r) => r.state === "failed").length;
  const progress = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>Bulk-import nodes</Dialog.Title>
          <p className={styles.subtitle}>
            Running the per-node import wizard against every node class still
            marked <em>needs config</em>. Failures are skipped — the rest
            continues. Closing the modal aborts the run.
          </p>

          <div className={styles.progressRow}>
            <span>
              {running
                ? `${done} / ${total}`
                : `${succeeded} ok · ${failed} skipped · ${total} total`}
            </span>
            <div className={styles.progressBar} aria-hidden>
              <div
                className={styles.progressFill}
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          <div className={styles.list}>
            {rows.map((row, idx) => (
              <div
                key={row.classType}
                className={styles.row}
                data-state={row.state}
              >
                <RowIcon state={row.state} active={idx === cursor && running} />
                <span className={styles.rowLabel}>{row.displayName}</span>
                {row.detail && (
                  <span className={styles.rowDetail} title={row.detail}>
                    {row.detail}
                  </span>
                )}
              </div>
            ))}
          </div>

          {!running && total > 0 && (
            <div className={styles.summary}>
              {failed > 0
                ? `${succeeded} imported, ${failed} skipped. Review failed entries in the catalog or re-run the wizard per-node.`
                : `Imported all ${succeeded} node${succeeded === 1 ? "" : "s"}.`}
            </div>
          )}

          <div className={styles.foot}>
            {running ? (
              <Button onClick={cancel}>Cancel</Button>
            ) : (
              <Button onClick={() => onOpenChange(false)}>Close</Button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}


function RowIcon({ state, active }: { state: RowState; active: boolean }) {
  switch (state) {
    case "succeeded":
      return <Icon name="Check" size={13} strokeWidth={2.5} />;
    case "failed":
      return <Icon name="AlertCircle" size={13} strokeWidth={2} />;
    case "running":
      return <Icon name="RotateCw" size={13} strokeWidth={2} />;
    default:
      return (
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: 999,
            background: "currentColor",
            opacity: active ? 0.6 : 0.3,
          }}
        />
      );
  }
}
