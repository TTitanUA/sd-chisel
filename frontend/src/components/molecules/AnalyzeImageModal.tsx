import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  sessionsApi,
  useSessionInvalidation,
  type Session,
  type SourceImage,
} from "@/api/sessions";
import { useLmStudioConfig } from "@/api/settings";
import styles from "./AnalyzeImageModal.module.css";

export function AnalyzeImageModal({
  session,
  image,
  open,
  onOpenChange,
}: {
  session: Session;
  image: SourceImage;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const cfg = useLmStudioConfig();
  const invalidate = useSessionInvalidation();
  const [refining, setRefining] = useState(image.analysis_prompt ?? "");
  const [error, setError] = useState<string | null>(null);

  // Reset the textarea whenever the modal is reopened for the same/another image.
  useEffect(() => {
    if (open) {
      setRefining(image.analysis_prompt ?? "");
      setError(null);
    }
  }, [open, image.id, image.analysis_prompt]);

  const analyze = useMutation({
    mutationFn: () =>
      sessionsApi.analyzeSource(
        session.id,
        image.id,
        refining.trim() ? refining.trim() : null,
      ),
    onSuccess: () => {
      invalidate.session(session.id);
      onOpenChange(false);
    },
    onError: (err) => setError(String(err)),
  });

  const lmConfigured = !!cfg.data?.configured;
  const hasVlModel = !!session.vl_model_name;
  const blockReason =
    !hasVlModel ? "No VL model selected — open Session settings"
    : !lmConfigured ? "LMStudio is not configured — open Settings"
    : null;
  const isReanalyze = !!image.analysis;

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !analyze.isPending && onOpenChange(v)}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.panel} aria-describedby={undefined}>
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>
              {isReanalyze ? "Re-analyze" : "Analyze"} · {image.original_filename}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.closeBtn}
                aria-label="Close"
                disabled={analyze.isPending}
              >
                <Icon name="X" />
              </button>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            <label className={styles.labelBlock}>
              <span>Refining instruction (optional)</span>
              <textarea
                className={styles.textarea}
                value={refining}
                onChange={(e) => setRefining(e.currentTarget.value)}
                placeholder="e.g. focus on the cat in the foreground; ignore the background text"
                rows={5}
                disabled={analyze.isPending}
                autoFocus
              />
            </label>
            <div className={styles.help}>
              The VL model always uses its standard i2i system prompt. Leave
              this empty to use the default user-side ask, or type your own —
              it is sent verbatim, replacing the default.
            </div>
            {blockReason && (
              <div className={styles.warn} role="alert">{blockReason}</div>
            )}
            {error && (
              <div className={styles.error} role="alert">{error}</div>
            )}
          </div>
          <div className={styles.foot}>
            <Button
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={analyze.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              icon={<Icon name="Sparkles" size={12} />}
              onClick={() => analyze.mutate()}
              disabled={analyze.isPending || !!blockReason}
            >
              {analyze.isPending
                ? "Analyzing…"
                : isReanalyze ? "Re-analyze" : "Analyze"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
