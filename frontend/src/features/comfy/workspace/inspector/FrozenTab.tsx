import {
  SLOT_BINDING_LABEL,
  SLOT_KIND_LABEL,
  useSlotMap,
  type SlotDefinition,
} from "@/api/comfy";
import type { Session } from "@/api/sessions";
import styles from "./InspectorRail.module.css";

/** Per-slot frozen-override editor. Mock PR is read-only — Live PR
 *  will let the user override the saved slot-map value with a session-
 *  scoped one (kind-appropriate widget) and toggle "use slot-map value"
 *  per slot. Edits do not write back to the slot map. */
export function FrozenTab({ session }: { session: Session }) {
  const query = useSlotMap(session.id);

  if (query.isLoading) {
    return <div className={styles.empty}>Loading slot map…</div>;
  }
  if (query.isError || !query.data) {
    return <div className={styles.empty}>Slot map unavailable.</div>;
  }

  const frozenSlots = query.data.slot_map.slots.filter(
    (s: SlotDefinition) => s.binding === "frozen",
  );

  return (
    <>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Frozen overrides</span>
      </div>
      {frozenSlots.length === 0 ? (
        <div className={styles.empty}>
          This workflow has no <strong>frozen</strong> slots — nothing to
          override per session.
        </div>
      ) : (
        <div className={styles.empty}>
          {frozenSlots.map((s) => (
            <div key={s.label} className={styles.slotRow}>
              <span className={styles.slotLabel}>{s.label}</span>
              <span className={styles.chip}>{SLOT_KIND_LABEL[s.kind]}</span>
              <span className={styles.chip} data-binding={s.binding}>
                {SLOT_BINDING_LABEL[s.binding]}
              </span>
            </div>
          ))}
          <p>
            Per-session override editor lands in Phase 3 (Live PR). Until then,
            edit the slot-map directly via the Slots tab ✏ — those values are
            workflow-wide.
          </p>
        </div>
      )}
    </>
  );
}
