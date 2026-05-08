/** When a node-tree input is clicked, show its current binding state.
 *  Modal-style; closes on backdrop click. See
 *  docs/comfy-agents-ui-mock-plan.md. */
import { useMemo } from "react";
import type { SlotDefinition } from "@/api/comfy";
import { useComfy } from "../state/useComfy";
import styles from "./InputDrawer.module.css";

export function InputDrawer({
  open,
  nodeId,
  inputName,
  onClose,
}: {
  open: boolean;
  nodeId: string | null;
  inputName: string | null;
  onClose: () => void;
}) {
  const { slotMap, agents } = useComfy();

  const slot = useMemo<SlotDefinition | null>(() => {
    if (!slotMap || !nodeId || !inputName) return null;
    return (
      slotMap.slot_map.slots.find(
        (s) => s.origin.node_id === nodeId && s.origin.input_name === inputName,
      ) ?? null
    );
  }, [slotMap, nodeId, inputName]);

  const boundAgent = useMemo(() => {
    if (!slot) return null;
    for (const a of agents) {
      for (const out of a.output_slots) {
        if (out.bound_to?.workflow_slot_label === slot.label) {
          return { agent: a, slot: out };
        }
      }
    }
    return null;
  }, [slot, agents]);

  if (!open || !nodeId || !inputName) return null;

  return (
    <div className={styles.backdrop} onClick={onClose}>
      <div className={styles.panel} onClick={(e) => e.stopPropagation()}>
        <header className={styles.header}>
          <span className={styles.target}>
            <code>#{nodeId}</code> · <code>{inputName}</code>
          </span>
          <button className={styles.close} onClick={onClose}>
            ×
          </button>
        </header>
        <div className={styles.body}>
          {!slot ? (
            <div className={styles.unbound}>
              No workflow slot is mapped to this input. Use the slot-map editor
              to declare it.
            </div>
          ) : (
            <>
              <div className={styles.section}>
                <div className={styles.label}>Workflow slot</div>
                <div>
                  <strong>{slot.label}</strong>{" "}
                  <span className={styles.dim}>
                    ({slot.kind} · binding={slot.binding})
                  </span>
                </div>
                {slot.description && (
                  <div className={styles.description}>{slot.description}</div>
                )}
              </div>

              {slot.binding === "llm" && (
                <div className={styles.section}>
                  <div className={styles.label}>Filled by</div>
                  {boundAgent ? (
                    <div>
                      <strong>{boundAgent.agent.name}</strong> ›{" "}
                      <code>{boundAgent.slot.label}</code>
                      <div className={styles.preview}>
                        {boundAgent.slot.last_value === null ||
                        boundAgent.slot.last_value === undefined
                          ? "(not run yet)"
                          : preview(boundAgent.slot.last_value)}
                      </div>
                    </div>
                  ) : (
                    <em>No agent bound — workflow Generate will fail.</em>
                  )}
                </div>
              )}

              {slot.binding === "frozen" && (
                <div className={styles.section}>
                  <div className={styles.label}>Frozen value</div>
                  <code>{preview((slot.metadata as Record<string, unknown>)?.value)}</code>
                </div>
              )}

              {slot.binding === "user_image" && (
                <div className={styles.section}>
                  <div className={styles.label}>User image</div>
                  <em>Picked from session sources at run time.</em>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function preview(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v.length > 320 ? v.slice(0, 320) + "…" : v;
  return String(v);
}
