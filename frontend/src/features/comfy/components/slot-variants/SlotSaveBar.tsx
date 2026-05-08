/** Shared save / reset / status footer for the slot-mapping variants.
 *  Pulled out so each variant's main component can stay focused on
 *  layout. See docs/comfy-agents-ui-mock-plan.md. */
import styles from "./SlotSaveBar.module.css";

export function SlotSaveBar({
  dirty,
  saving,
  saved,
  saveError,
  onSave,
  onReset,
}: {
  dirty: boolean;
  saving: boolean;
  saved: boolean;
  saveError: string | null;
  onSave: () => void;
  onReset: () => void;
}) {
  return (
    <div className={styles.bar}>
      <button
        type="button"
        className={styles.save}
        disabled={!dirty || saving}
        onClick={onSave}
      >
        {saving ? "Saving…" : "Save"}
      </button>
      {dirty && !saving && (
        <button type="button" className={styles.reset} onClick={onReset}>
          Reset
        </button>
      )}
      {!dirty && saved && <span className={styles.savedHint}>Saved.</span>}
      {saveError && <span className={styles.error}>{saveError}</span>}
    </div>
  );
}
