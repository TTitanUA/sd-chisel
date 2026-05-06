import {
  SLOT_BINDING_LABEL,
  SLOT_KIND_LABEL,
  useSlotMap,
  type SlotDefinition,
} from "@/api/comfy";
import type { Session } from "@/api/sessions";
import { Icon } from "@/components/atoms/Icon";
import styles from "./InspectorRail.module.css";

/** Read-only summary of the workflow slot map, grouped by `group`.
 *
 * The ✏ icon at the section header opens the slot-map drawer
 * (the editor is the same body that used to live behind the
 * "Edit slots" header button). */
export function SlotsTab({
  session,
  onEditSlots,
}: {
  session: Session;
  onEditSlots: () => void;
}) {
  const query = useSlotMap(session.id);

  if (query.isLoading) {
    return <div className={styles.empty}>Loading slot map…</div>;
  }
  if (query.isError || !query.data) {
    return <div className={styles.empty}>Slot map unavailable.</div>;
  }

  const slots = query.data.slot_map.slots;

  return (
    <>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Slots</span>
        <button
          type="button"
          className={styles.editButton}
          onClick={onEditSlots}
          aria-label="Edit slot map"
          title="Edit slot map"
        >
          <Icon name="Pencil" size={12} />
        </button>
      </div>
      {slots.length === 0 ? (
        <div className={styles.empty}>
          No slots declared yet. Open the editor with the ✏ icon and add a
          slot for each workflow input you want to fill at generate time.
        </div>
      ) : (
        groupSlots(slots).map(([group, members]) => (
          <div key={group ?? "__ungrouped__"} className={styles.slotGroup}>
            {group && <div className={styles.slotGroupHeader}>{group}</div>}
            {members.map((slot) => (
              <div key={slot.label} className={styles.slotRow}>
                <span className={styles.slotLabel} title={slot.description ?? slot.label}>
                  {slot.label}
                </span>
                <span className={styles.chip}>
                  {SLOT_KIND_LABEL[slot.kind]}
                </span>
                <span className={styles.chip} data-binding={slot.binding}>
                  {SLOT_BINDING_LABEL[slot.binding]}
                </span>
              </div>
            ))}
          </div>
        ))
      )}
    </>
  );
}

function groupSlots(
  slots: SlotDefinition[],
): Array<[string | null, SlotDefinition[]]> {
  const map = new Map<string | null, SlotDefinition[]>();
  for (const s of slots) {
    const key = s.group?.trim() || null;
    const list = map.get(key) ?? [];
    list.push(s);
    map.set(key, list);
  }
  const entries = Array.from(map.entries());
  entries.sort(([a], [b]) => {
    if (a === b) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    return a.localeCompare(b);
  });
  for (const [, members] of entries) {
    members.sort((a, b) => {
      const oa = a.ordinal ?? Number.MAX_SAFE_INTEGER;
      const ob = b.ordinal ?? Number.MAX_SAFE_INTEGER;
      if (oa !== ob) return oa - ob;
      return a.label.localeCompare(b.label);
    });
  }
  return entries;
}
