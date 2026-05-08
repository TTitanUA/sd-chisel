/** Tree slot-mapping variant: side drawer.
 *
 *  Click any input → the editor opens in the always-visible right
 *  column (col 3 of the shared `MappingTreeShell`). The drawer mode
 *  basically promotes col 3 to be the primary editor — clicking
 *  rapidly between inputs swaps its contents without losing tree
 *  scroll position. See docs/comfy-agents-ui-mock-plan.md.
 */
import {
  SLOT_KIND_LABEL,
  type CandidateBuckets,
  type Workflow,
} from "@/api/comfy";
import { useComfy } from "../../state/useComfy";
import type { SlotDraftHelpers } from "../slot-variants/useSlotDraft";
import { MappingTreeShell } from "./MappingTreeShell";
import {
  formatValue,
  formatValueFull,
  resolveLiveValue,
} from "./tree-helpers";
import styles from "./MappingTreeDrawer.module.css";

export function MappingTreeDrawer({
  workflow,
  helpers,
  candidates,
}: {
  workflow: Workflow | null | undefined;
  helpers: SlotDraftHelpers;
  candidates: CandidateBuckets | null;
}) {
  // Pull the same context the side-drawer editor uses so the node
  // cards can show the *effective* value (whatever the workflow will
  // actually receive at Generate time) rather than the workflow's
  // stored snapshot.
  const { agents, sourceSlots, session } = useComfy();
  return (
    <MappingTreeShell
      workflow={workflow}
      helpers={helpers}
      candidates={candidates}
      treeLabel="Tree · side drawer"
    >
      {({ active, setActive, rows }) => (
        <div className={styles.tree}>
          {rows.length === 0 && (
            <div className={styles.empty}>
              {workflow
                ? "This workflow exposes no fillable inputs."
                : "Workflow not loaded."}
            </div>
          )}
          {rows.map((node) => (
            <div key={node.nodeId} className={styles.node}>
              <div className={styles.nodeHead}>
                <span className={styles.nodeId}>#{node.nodeId}</span>
                <span className={styles.classType}>{node.classType}</span>
                {node.title && (
                  <span className={styles.title}>{node.title}</span>
                )}
              </div>
              <div className={styles.inputs}>
                {node.inputs.map((input) => {
                  const isActive =
                    active?.nodeId === node.nodeId &&
                    active.inputName === input.name;
                  const live = resolveLiveValue(input, {
                    agents,
                    sourceSlots,
                    session,
                  });
                  const placeholder =
                    live.source === "llm" ? "no value yet — run agent" : "—";
                  const valueText =
                    live.value === null || live.value === undefined
                      ? placeholder
                      : formatValue(live.value);
                  return (
                    <button
                      key={input.name}
                      type="button"
                      className={`${styles.inputRow} ${isActive ? styles.active : ""}`}
                      data-mapped={!!input.mappedSlot}
                      onClick={() =>
                        setActive({
                          nodeId: node.nodeId,
                          inputName: input.name,
                        })
                      }
                    >
                      <span className={styles.inputName}>{input.name}</span>
                      <span
                        className={styles.inputValue}
                        title={formatValueFull(live.value)}
                      >
                        {valueText}
                      </span>
                      {input.mappedSlot ? (
                        <span
                          className={styles.pill}
                          data-binding={input.mappedSlot.binding}
                        >
                          ↳ {input.mappedSlot.label}
                        </span>
                      ) : input.candidate ? (
                        <span className={styles.addHint}>
                          + map ({SLOT_KIND_LABEL[input.candidate.kind]})
                        </span>
                      ) : (
                        <span className={styles.dim}>(unsupported)</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </MappingTreeShell>
  );
}
