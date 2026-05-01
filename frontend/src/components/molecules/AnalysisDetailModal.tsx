import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import type { SourceImage } from "@/api/sessions";
import styles from "./AnalysisDetailModal.module.css";

export function AnalysisDetailModal({
  image,
  open,
  onOpenChange,
}: {
  image: SourceImage;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.panel} aria-describedby={undefined}>
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>
              {image.original_filename}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.closeBtn} aria-label="Close">
                <Icon name="X" />
              </button>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            {image.analysis ? (
              <pre className={styles.text}>{image.analysis}</pre>
            ) : (
              <div className={styles.empty}>Not analyzed yet.</div>
            )}
            {image.analysis_prompt && (
              <div className={styles.refining}>
                <div className={styles.refiningHead}>Refining instruction</div>
                <div className={styles.refiningBody}>{image.analysis_prompt}</div>
              </div>
            )}
          </div>
          <div className={styles.foot}>
            <Button type="button" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
