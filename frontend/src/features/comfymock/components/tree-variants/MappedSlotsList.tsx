/** Left-hand list of currently-mapped workflow slots (col 1) shared
 *  by every d-tree-* variant.
 *
 *  Each row surfaces:
 *  - label / kind / binding pill
 *  - origin <node>.<input> (so the user can locate it in the tree)
 *  - filler hint:
 *    - binding=llm → which agent fills it
 *    - binding=user_image → which source slot it references
 *    - binding=frozen → the frozen value
 *
 *  Clicking a row jumps the centre tree's `active` to that slot's
 *  origin, opening the editor in col 3. See
 *  docs/comfy-agents-ui-mock-plan.md.
 */
import {
  SLOT_BINDING_LABEL,
  SLOT_KIND_LABEL,
  type SlotDefinition,
} from "@/api/comfy";
import { useComfyMock } from "../../state/useComfyMock";
import { FillerHint, SourceFillerHint } from "../slot-variants/FillerHint";
import { fillerFor, sourceFillerFor } from "../slot-variants/slot-helpers";
import type { ActiveInput } from "./InputContextPanel";
import styles from "./MappingTreeShell.module.css";

export function MappedSlotsList({
  slots,
  active,
  onActivate,
}: {
  slots: SlotDefinition[];
  active: ActiveInput | null;
  onActivate: (next: ActiveInput) => void;
}) {
  const { agents, sourceSlots, session } = useComfyMock();
  if (slots.length === 0) {
    return (
      <div className={styles.slotsEmpty}>
        No slots mapped yet. Click <strong>+ map</strong> on an input in
        the tree to create one.
      </div>
    );
  }
  return (
    <div className={styles.slotsList}>
      {slots.map((slot) => {
        const isActive =
          active?.nodeId === slot.origin.node_id &&
          active.inputName === slot.origin.input_name;
        const filler =
          slot.binding === "llm" ? fillerFor(slot.label, agents) : null;
        const source =
          slot.binding === "user_image"
            ? sourceFillerFor(slot, sourceSlots, session)
            : null;
        const frozenValue = (slot.metadata as Record<string, unknown>)?.value;
        return (
          <button
            key={`${slot.origin.node_id}:${slot.origin.input_name}`}
            type="button"
            className={`${styles.slotCard} ${isActive ? styles.slotCardActive : ""}`}
            onClick={() =>
              onActivate({
                nodeId: slot.origin.node_id,
                inputName: slot.origin.input_name,
              })
            }
            title={`Edit ${slot.label}`}
          >
            <div className={styles.slotCardHead}>
              <span className={styles.slotLabel}>{slot.label}</span>
              <span className={styles.slotPill} data-binding={slot.binding}>
                {SLOT_BINDING_LABEL[slot.binding]}
              </span>
            </div>
            <div className={styles.slotOrigin}>
              <code>#{slot.origin.node_id}</code>.{slot.origin.input_name}{" "}
              · {SLOT_KIND_LABEL[slot.kind]}
            </div>
            {slot.binding === "llm" && <FillerHint filler={filler} />}
            {slot.binding === "user_image" && (
              <SourceFillerHint source={source} />
            )}
            {slot.binding === "frozen" && frozenValue !== undefined && (
              <div className={styles.slotOrigin}>
                value: <code>{formatFrozen(frozenValue)}</code>
              </div>
            )}
          </button>
        );
      })}
    </div>
  );
}

function formatFrozen(v: unknown): string {
  if (v === null || v === undefined) return "—";
  const s =
    typeof v === "string" ? v : typeof v === "number" || typeof v === "boolean" ? String(v) : JSON.stringify(v);
  return s.length > 28 ? s.slice(0, 28) + "…" : s;
}
