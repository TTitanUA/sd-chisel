import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import {
  ActionSettingsModal,
} from "@/components/organisms/ActionSettingsModal/ActionSettingsModal";
import type { Action, Session } from "@/api/sessions";
import styles from "@/components/organisms/ActionSettingsModal/ActionSettingsModal.module.css";

/**
 * Gear button placed next to an LLM-action trigger. Clicking it opens the
 * per-action sampling-settings modal in either session-override mode (when
 * a ``session`` is given) or app-defaults mode.
 */
export function ActionSettingsButton({
  action,
  session,
  size = 12,
  disabled = false,
  title,
}: {
  action: Action;
  session?: Session;
  size?: number;
  disabled?: boolean;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const tip = title ?? (session ? "Override sampling for this session" : "Edit app default");
  return (
    <>
      <button
        type="button"
        className={styles.gearBtn}
        onClick={() => setOpen(true)}
        disabled={disabled}
        aria-label={tip}
        title={tip}
      >
        <Icon name="Settings" size={size} />
      </button>
      {open && (
        <ActionSettingsModal
          mode={session ? { kind: "session", session, action } : { kind: "default", action }}
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}
