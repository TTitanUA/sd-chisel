/** One row in the agent's output-slot list. Shows kind chip, label,
 *  binding state, and a preview of the last_value. Click → open the
 *  per-slot detail modal (TODO when the layout calls for it). See
 *  docs/comfy-agents-ui-mock-plan.md. */
import type { AgentOutputSlot } from "@/api/comfy";
import { SLOT_KIND_LABEL } from "@/api/comfy";
import styles from "./OutputSlotRow.module.css";

export function OutputSlotRow({
  slot,
  onUnbind,
  onDelete,
}: {
  slot: AgentOutputSlot;
  onUnbind?: () => void;
  onDelete?: () => void;
}) {
  const preview = slotPreview(slot);
  const filled =
    slot.last_value !== null && slot.last_value !== undefined && slot.kind;
  return (
    <div className={`${styles.row} ${filled ? styles.filled : styles.empty}`}>
      <div className={styles.head}>
        <span className={styles.label}>{slot.label}</span>
        {slot.kind && (
          <span className={styles.kind}>{SLOT_KIND_LABEL[slot.kind]}</span>
        )}
        <span className={styles.origin}>{slot.origin}</span>
        {slot.bound_to && (
          <span className={styles.bind}>
            ↳ {slot.bound_to.workflow_slot_label}
          </span>
        )}
      </div>
      {slot.description && (
        <div className={styles.description}>{slot.description}</div>
      )}
      <div className={styles.preview}>
        {preview ?? <em className={styles.placeholder}>no value yet</em>}
      </div>
      {(onUnbind || onDelete) && (
        <div className={styles.actions}>
          {onUnbind && slot.bound_to && (
            <button type="button" onClick={onUnbind}>
              unbind
            </button>
          )}
          {onDelete && (
            <button type="button" onClick={onDelete}>
              delete
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function slotPreview(slot: AgentOutputSlot): string | null {
  const v = slot.last_value;
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return "(unserialisable)";
  }
}
