import {
  SLOT_KIND_LABEL,
  useSlotMap,
  type SlotDefinition,
} from "@/api/comfy";
import type { Session } from "@/api/sessions";
import styles from "./InspectorRail.module.css";

/** Per-slot image-binding picker, one row per `binding=user_image`
 *  slot. Mock PR is read-only — Live PR will let the user pick a
 *  source image per slot, persist the choice as session state, and
 *  feed it into Phase 3's `payload_overrides[<label>]`. */
export function BindingsTab({ session }: { session: Session }) {
  const query = useSlotMap(session.id);

  if (query.isLoading) {
    return <div className={styles.empty}>Loading slot map…</div>;
  }
  if (query.isError || !query.data) {
    return <div className={styles.empty}>Slot map unavailable.</div>;
  }

  const imageSlots = query.data.slot_map.slots.filter(
    (s: SlotDefinition) => s.binding === "user_image",
  );

  return (
    <>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Image bindings</span>
      </div>
      {imageSlots.length === 0 ? (
        <div className={styles.empty}>
          This workflow has no <strong>session image</strong> slots — nothing
          to bind. If you expect one, open the slot-map editor (Slots tab ✏)
          and switch a slot's binding to <em>session image</em>.
        </div>
      ) : (
        <div className={styles.empty}>
          <p>
            {imageSlots.length} image-binding slot
            {imageSlots.length === 1 ? "" : "s"} detected:
          </p>
          {imageSlots.map((s) => (
            <div key={s.label} className={styles.slotRow}>
              <span className={styles.slotLabel}>{s.label}</span>
              <span className={styles.chip}>{SLOT_KIND_LABEL[s.kind]}</span>
              <span className={styles.chip}>not picked</span>
            </div>
          ))}
          <p>
            Per-slot source-image picker lands in Phase 3 (Live PR). Until
            then, drop images into the Sources tab and they'll be available
            once the picker ships.
          </p>
        </div>
      )}
    </>
  );
}
