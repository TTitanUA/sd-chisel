import { useState } from "react";
import { Icon } from "@/components/atoms/Icon";
import {
  ActionSettingsModal,
} from "@/components/organisms/ActionSettingsModal/ActionSettingsModal";
import type { Action, Session } from "@/api/sessions";
import type { DefaultAction } from "@/api/settings";
import styles from "@/components/organisms/ActionSettingsModal/ActionSettingsModal.module.css";

/**
 * Gear button placed next to an LLM-action trigger. Clicking it opens the
 * per-action sampling-settings modal in either session-override mode (when
 * a ``session`` is given) or app-defaults mode. Default mode accepts the
 * wider ``DefaultAction`` so global actions like ``comfy_import`` can be
 * edited from the LM Studio settings page.
 */
export function ActionSettingsButton({
  action,
  session,
  size = 12,
  disabled = false,
  title,
}: {
  action: Action | DefaultAction;
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
          mode={
            session
              // session-mode requires the narrow Action; the cast is
              // safe because callers only pass ``session`` together
              // with a session-scoped action key.
              ? { kind: "session", session, action: action as Action }
              : { kind: "default", action }
          }
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </>
  );
}
