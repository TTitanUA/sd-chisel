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
import type { SlotDraftHelpers } from "../slot-variants/useSlotDraft";
import { MappingTreeShell } from "./MappingTreeShell";
import { formatValue } from "./tree-helpers";
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
                  const valueText = formatValue(input.rawValue);
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
                        title={
                          input.rawValue == null
                            ? ""
                            : typeof input.rawValue === "string"
                              ? input.rawValue
                              : JSON.stringify(input.rawValue)
                        }
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
