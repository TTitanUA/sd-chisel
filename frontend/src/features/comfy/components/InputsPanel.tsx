/** Read-only summary of the workflow's user_image / frozen slots —
 *  inputs that the workflow expects from the session rather than from
 *  an LLM agent. user_image slots resolve through the per-session
 *  Source-slot table (state/source-slots.ts) — slot.metadata.source_slot_id
 *  → SourceSlot.source_image_id → session.source_images. See
 *  docs/comfy-agents-ui-mock-plan.md. */
import { useComfy } from "../state/useComfy";
import { SourceFillerHint } from "./slot-variants/FillerHint";
import { sourceFillerFor } from "./slot-variants/slot-helpers";
import styles from "./InspectorPanels.module.css";

export function InputsPanel() {
  const { slotMap, session, sourceSlots } = useComfy();
  const slots = slotMap?.slot_map.slots ?? [];
  const inputSlots = slots.filter(
    (s) => s.binding === "user_image" || s.binding === "frozen",
  );
  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>Inputs ({inputSlots.length})</span>
      </div>
      <div className={styles.body}>
        <div className={styles.list}>
          {inputSlots.length === 0 && (
            <div className={styles.empty}>
              No user-image / frozen slots in this workflow.
            </div>
          )}
          {inputSlots.map((s) => (
            <div key={s.label} className={styles.row}>
              <div className={styles.rowHead}>
                <strong>{s.label}</strong>
                <span className={styles.chip}>{s.binding}</span>
              </div>
              {s.binding === "frozen" && (
                <div className={styles.dim}>
                  value:{" "}
                  {String((s.metadata as Record<string, unknown>)?.value)}
                </div>
              )}
              {s.binding === "user_image" && (
                <SourceFillerHint
                  source={sourceFillerFor(s, sourceSlots, session)}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
