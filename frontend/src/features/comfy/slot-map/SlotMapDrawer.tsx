import * as Dialog from "@radix-ui/react-dialog";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { ComfySlotMappingPanel } from "./ComfySlotMappingPanel";
import styles from "./SlotMapDrawer.module.css";

/** Right-side drawer that wraps the existing slot-map editor body.
 *
 * Replaces the Phase 2.5 full-screen step. The editor itself is
 * untouched — only its page chrome (`onBack` / `onContinue`) is
 * stripped here, since there's no step machine left to advance. */
export function SlotMapDrawer({
  sessionId,
  open,
  onOpenChange,
}: {
  sessionId: string;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.drawer}
          aria-describedby={undefined}
          onInteractOutside={(e) => {
            // Allow clicking outside to close — but not while a save is
            // pending. The panel itself surfaces the dirty state; a
            // close-with-unsaved-changes guard can land later.
            void e;
          }}
        >
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>
              Slot map
            </Dialog.Title>
            <Dialog.Close asChild>
              <Button
                size="sm"
                icon={<Icon name="X" size={12} />}
                aria-label="Close slot-map drawer"
              >
                Close
              </Button>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            <ComfySlotMappingPanel sessionId={sessionId} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
