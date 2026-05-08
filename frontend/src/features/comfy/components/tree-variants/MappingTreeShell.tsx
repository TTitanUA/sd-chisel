/** 3-column container shared by every d-tree-* variant.
 *
 *  Layout mirrors the D-base IDE shell:
 *  - **col 1 (260 px)**: list of currently mapped slots, with filler
 *    hints surfacing which agent fills each binding=llm slot and
 *    which source slot fills each binding=user_image slot.
 *  - **col 2 (1fr)**: variant-specific tree (children prop). Each
 *    variant renders its own tree+row UX here; the shell only owns
 *    layout, header, and active-input state.
 *  - **col 3 (320 px)**: shared `InputContextPanel` editor for the
 *    currently active input. Always visible — when nothing is active
 *    we render a placeholder so the 3-col grid stays stable.
 *
 *  See docs/comfy-agents-ui-mock-plan.md.
 */
import { useMemo, useState, type ReactNode } from "react";
import {
  useOutputSlotMap,
  type CandidateBuckets,
  type Workflow,
} from "@/api/comfy";
import { useComfy } from "../../state/useComfy";
import { SlotSaveBar } from "../slot-variants/SlotSaveBar";
import type { SlotDraftHelpers } from "../slot-variants/useSlotDraft";
import { InputContextPanel, type ActiveInput } from "./InputContextPanel";
import { MappedSlotsList } from "./MappedSlotsList";
import { buildMappingRows } from "./tree-helpers";
import styles from "./MappingTreeShell.module.css";

export type MappingTreeShellChildProps = {
  active: ActiveInput | null;
  setActive: (next: ActiveInput | null) => void;
  rows: ReturnType<typeof buildMappingRows>;
};

export function MappingTreeShell({
  workflow,
  helpers,
  candidates,
  treeLabel,
  children,
}: {
  workflow: Workflow | null | undefined;
  helpers: SlotDraftHelpers;
  candidates: CandidateBuckets | null;
  /** "Tree · inline expand", "Tree · drawer", … — shown in col-2 head. */
  treeLabel: string;
  children: (props: MappingTreeShellChildProps) => ReactNode;
}) {
  const { session } = useComfy();
  const outputSlotMapQuery = useOutputSlotMap(session.id);
  const [active, setActive] = useState<ActiveInput | null>(null);
  const rows = useMemo(
    () =>
      buildMappingRows(
        workflow,
        helpers.draft ?? [],
        candidates,
        outputSlotMapQuery.data?.output_slot_map ?? null,
      ),
    [
      workflow,
      helpers.draft,
      candidates,
      outputSlotMapQuery.data?.output_slot_map,
    ],
  );
  const draft = helpers.draft ?? [];
  return (
    <div className={styles.outer}>
      <div className={styles.shell}>
        <aside className={`${styles.col} ${styles.colLeft}`}>
          <header className={styles.colHead}>
            <span className={styles.colTitle}>Mapped slots</span>
            <span className={styles.colCount}>{draft.length}</span>
          </header>
          <div className={styles.colBody}>
            <MappedSlotsList
              slots={draft}
              active={active}
              onActivate={setActive}
            />
          </div>
        </aside>

        <section className={styles.col}>
          <header className={styles.colHead}>
            <span className={styles.colTitle}>{treeLabel}</span>
            <span className={styles.colCount}>{rows.length} nodes</span>
          </header>
          <div className={styles.colBody}>
            {children({ active, setActive, rows })}
          </div>
        </section>

        <aside className={`${styles.col} ${styles.colRight}`}>
          <header className={styles.colHead}>
            <span className={styles.colTitle}>Editor</span>
          </header>
          <div className={styles.colBody}>
            <InputContextPanel active={active} rows={rows} helpers={helpers} />
          </div>
        </aside>
      </div>
      <SlotSaveBar
        dirty={helpers.dirty}
        saving={helpers.saving}
        saved={helpers.saved}
        saveError={helpers.saveError}
        onSave={helpers.save}
        onReset={helpers.reset}
      />
    </div>
  );
}
