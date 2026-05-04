import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  IMPORT_STAGES,
  IMPORT_STAGE_LABEL,
  runImport,
  type ImportEvent,
  type ImportStage,
} from "@/api/comfy";
import styles from "./ComfyImportModal.module.css";

type StageState = "pending" | "running" | "succeeded" | "failed";

type StageStatus = {
  state: StageState;
  detail?: string;
  error?: string;
};

const INITIAL_STATUS: Record<ImportStage, StageStatus> = {
  locate_pack: { state: "pending" },
  fetch_schema: { state: "pending" },
  enrich_llm: { state: "pending" },
  persist: { state: "pending" },
};


export function ComfyImportModal({
  classType,
  classDisplayName,
  open,
  onOpenChange,
  onImported,
}: {
  classType: string;
  classDisplayName?: string;
  open: boolean;
  onOpenChange: (value: boolean) => void;
  onImported?: () => void;
}) {
  const client = useQueryClient();
  const [statuses, setStatuses] = useState<Record<ImportStage, StageStatus>>(
    INITIAL_STATUS,
  );
  const [done, setDone] = useState(false);
  const [running, setRunning] = useState(false);
  const [topError, setTopError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = () => {
    setStatuses(INITIAL_STATUS);
    setDone(false);
    setTopError(null);
  };

  useEffect(() => {
    if (open) {
      reset();
      void start();
    } else {
      abortRef.current?.abort();
    }
    return () => {
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, classType]);

  async function start() {
    setRunning(true);
    setStatuses(INITIAL_STATUS);
    setTopError(null);
    setDone(false);

    const abort = new AbortController();
    abortRef.current = abort;

    const handle = (event: ImportEvent) => {
      switch (event.type) {
        case "stage_started": {
          if (event.stage === "internal") return;
          setStatuses((prev) => ({
            ...prev,
            [event.stage]: { state: "running" },
          }));
          break;
        }
        case "stage_succeeded": {
          setStatuses((prev) => ({
            ...prev,
            [event.stage]: {
              state: "succeeded",
              detail: summariseSuccess(event.stage, event.data),
            },
          }));
          break;
        }
        case "stage_failed": {
          setStatuses((prev) => {
            if (event.stage === "internal") return prev;
            return {
              ...prev,
              [event.stage]: { state: "failed", error: event.error },
            };
          });
          setTopError(event.error);
          break;
        }
        case "done": {
          setDone(true);
          // Invalidate downstream queries so the catalog and readiness
          // panels reflect the new row immediately.
          void client.invalidateQueries({ queryKey: ["comfy"] });
          onImported?.();
          break;
        }
      }
    };

    try {
      await runImport(classType, handle, abort.signal);
    } catch (exc) {
      if (!abort.signal.aborted) {
        setTopError((exc as Error).message);
      }
    } finally {
      setRunning(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} aria-describedby={undefined}>
          <Dialog.Title className={styles.title}>
            Import node{" "}
            <span className={styles.classType}>
              {classDisplayName ?? classType}
            </span>
          </Dialog.Title>
          <p className={styles.subtitle}>
            The wizard locates the pack on disk, fetches the live INPUT_TYPES
            from ComfyUI, asks LMStudio for a short description, then writes
            a row to the catalog. You can edit the description and per-input
            notes from the Library afterward.
          </p>

          <div className={styles.stages}>
            {IMPORT_STAGES.map((stage) => (
              <StageRow
                key={stage}
                label={IMPORT_STAGE_LABEL[stage]}
                status={statuses[stage]}
              />
            ))}
          </div>

          {done && (
            <div className={styles.successBanner}>
              <Icon name="Check" size={14} />
              Import complete — the node is in the catalog and the readiness
              panel will refresh.
            </div>
          )}

          {topError && !done && !running && (
            <div className={styles.stageError} role="alert">{topError}</div>
          )}

          <div className={styles.foot}>
            {running ? (
              <Button
                onClick={() => {
                  abortRef.current?.abort();
                  setRunning(false);
                }}
              >
                Cancel
              </Button>
            ) : (
              <>
                <Button onClick={() => onOpenChange(false)}>
                  {done ? "Close" : "Dismiss"}
                </Button>
                {!done && (
                  <Button variant="primary" onClick={() => void start()}>
                    {topError ? "Retry" : "Run again"}
                  </Button>
                )}
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}


function StageRow({ label, status }: { label: string; status: StageStatus }) {
  return (
    <div className={styles.stage} data-state={status.state}>
      <span className={styles.stageIcon}>
        <StageIcon state={status.state} />
      </span>
      <div className={styles.stageBody}>
        <span className={styles.stageLabel}>{label}</span>
        {status.detail && <span className={styles.stageDetail}>{status.detail}</span>}
        {status.error && <span className={styles.stageError}>{status.error}</span>}
      </div>
    </div>
  );
}


function StageIcon({ state }: { state: StageState }) {
  switch (state) {
    case "succeeded":
      return <Icon name="Check" size={14} strokeWidth={2.5} />;
    case "failed":
      return <Icon name="AlertCircle" size={14} strokeWidth={2} />;
    case "running":
      return <Icon name="RotateCw" size={14} strokeWidth={2} />;
    default:
      return <span style={{ width: 8, height: 8, borderRadius: 999, background: "currentColor", opacity: 0.4 }} />;
  }
}


function summariseSuccess(
  stage: ImportStage, data: Record<string, unknown>,
): string | undefined {
  switch (stage) {
    case "locate_pack": {
      const pack = data.pack as { name?: string; is_builtin?: boolean } | undefined;
      if (!pack) return undefined;
      const tag = pack.is_builtin ? " (built-in)" : "";
      const readme = data.readme_present ? " · README found" : "";
      return `pack: ${pack.name}${tag}${readme}`;
    }
    case "fetch_schema": {
      const names = data.input_names as string[] | undefined;
      if (!names) return undefined;
      return `${names.length} input${names.length === 1 ? "" : "s"} discovered`;
    }
    case "enrich_llm": {
      const semantic = data.inputs_semantic as { notes: string | null }[] | undefined;
      const annotated = (semantic ?? []).filter((s) => s.notes !== null).length;
      return `${annotated} input note${annotated === 1 ? "" : "s"} captured`;
    }
    case "persist":
      return "row written to catalog";
    default:
      return undefined;
  }
}
