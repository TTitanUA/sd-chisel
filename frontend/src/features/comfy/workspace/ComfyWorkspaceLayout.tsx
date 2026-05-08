/** Comfy workspace IDE-like layout. Left vertical tab-bar with one
 *  button per panel (Agents / Inputs / Sources / Nodes / Chat); centre
 *  toggles between agent editor and the slot-mapping tree
 *  (drawer-style); bottom panel = gallery (collapsible, like a VSCode
 *  terminal).
 *
 *  Originally landed as Variant D of the ComfyMock playground — see
 *  docs/comfy-agents-ui-mock-plan.md for the variant comparison; the
 *  rest of the doc's mock-vs-real distinctions still apply (chat,
 *  per-agent /run and workflow Generate are emulated client-side
 *  until the matching backend endpoints land). */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { comfyApi } from "@/api/comfy";
import { AgentEditor } from "../components/AgentEditor";
import { AgentsList } from "../components/AgentsList";
import { ChatPanel } from "../components/ChatPanel";
import { GalleryPanel } from "../components/GalleryPanel";
import { InputDrawer } from "../components/InputDrawer";
import { InputsPanel } from "../components/InputsPanel";
import { KnobsStrip } from "../components/KnobsStrip";
import { OutputsPanel } from "../components/OutputsPanel";
import { useSlotDraft } from "../components/slot-variants/useSlotDraft";
import { MappingTreeDrawer } from "../components/tree-variants/MappingTreeDrawer";
import { SourcesPanel } from "../components/SourcesPanel";
import { useComfy } from "../state/useComfy";
import { useKnobs, type KnobSpec } from "../state/useKnobs";
import styles from "./ComfyWorkspaceLayout.module.css";

const KNOBS: KnobSpec[] = [
  { cssVar: "--vd-tab-w", label: "Tab bar width", default: 48, min: 36, max: 100, step: 2, unit: "px" },
  { cssVar: "--vd-side-col", label: "Side panel width", default: 400, min: 240, max: 720, step: 10, unit: "px" },
  { cssVar: "--vd-footer-h", label: "Gallery footer height", default: 220, min: 0, max: 600, step: 10, unit: "px" },
];

const LEFT_TABS = [
  { id: "agents", short: "Ag", label: "Agents" },
  { id: "inputs", short: "In", label: "Inputs" },
  { id: "outputs", short: "Ou", label: "Outputs" },
  { id: "sources", short: "Sr", label: "Sources" },
  { id: "chat", short: "Ch", label: "Chat" },
] as const;

type LeftTab = (typeof LEFT_TABS)[number]["id"];
type CenterMode = "agent" | "tree";

export function ComfyWorkspaceLayout({ knobsOpen }: { knobsOpen: boolean }) {
  const { session, agents, selectedAgentId, slotMap } = useComfy();
  const knobs = useKnobs("d", KNOBS);
  const workflowQuery = useQuery({
    queryKey: ["comfy", "workflows", session.comfy_workflow_id],
    queryFn: () => comfyApi.getWorkflow(session.comfy_workflow_id as string),
    enabled: !!session.comfy_workflow_id,
  });
  const [leftTab, setLeftTab] = useState<LeftTab>("agents");
  // Slot-mapping is the primary action of this layout, so default the
  // mode bar to "tree".
  const [centerMode, setCenterMode] = useState<CenterMode>("tree");
  const [footerOpen, setFooterOpen] = useState(true);
  const [drawerInput, setDrawerInput] = useState<{
    nodeId: string;
    inputName: string;
  } | null>(null);

  // The tree drawer needs its own slot-map draft so create / edit /
  // unmap can flow back to useSaveSlotMap.
  const treeHelpers = useSlotDraft(session.id);

  const selected = useMemo(
    () => agents.find((a) => a.id === selectedAgentId) ?? null,
    [agents, selectedAgentId],
  );

  return (
    <div className={styles.outer}>
      <div className={styles.shell}>
        <nav className={styles.tabs}>
          {LEFT_TABS.map((t) => (
            <button
              key={t.id}
              className={`${styles.tab} ${leftTab === t.id ? styles.active : ""}`}
              onClick={() => setLeftTab(t.id)}
              title={t.label}
            >
              {t.short}
            </button>
          ))}
        </nav>

        <aside className={styles.sidePanel}>
          {leftTab === "agents" && <AgentsList />}
          {leftTab === "inputs" && <InputsPanel />}
          {leftTab === "outputs" && <OutputsPanel />}
          {leftTab === "sources" && <SourcesPanel />}
          {leftTab === "chat" && <ChatPanel />}
        </aside>

        <main className={styles.main}>
          <div className={styles.modeBar}>
            <button
              className={centerMode === "agent" ? styles.modeActive : ""}
              onClick={() => setCenterMode("agent")}
            >
              Agent editor
            </button>
            <button
              className={centerMode === "tree" ? styles.modeActive : ""}
              onClick={() => setCenterMode("tree")}
            >
              Node tree
            </button>
          </div>
          <div className={styles.modeBody}>
            {centerMode === "agent" && (
              selected ? (
                <AgentEditor agent={selected} />
              ) : (
                <div className={styles.placeholder}>
                  Pick an agent in the left panel.
                </div>
              )
            )}
            {centerMode === "tree" && (
              <MappingTreeDrawer
                workflow={workflowQuery.data}
                helpers={treeHelpers}
                candidates={slotMap?.candidates ?? null}
              />
            )}
          </div>
        </main>
      </div>

      {footerOpen && (
        <footer className={styles.footer}>
          <button
            className={styles.footerToggle}
            onClick={() => setFooterOpen(false)}
          >
            ▾ hide gallery
          </button>
          <GalleryPanel />
        </footer>
      )}
      {!footerOpen && (
        <button
          className={styles.footerOpen}
          onClick={() => setFooterOpen(true)}
        >
          ▴ Gallery
        </button>
      )}

      {knobsOpen && <KnobsStrip knobs={knobs} />}
      <InputDrawer
        open={!!drawerInput}
        nodeId={drawerInput?.nodeId ?? null}
        inputName={drawerInput?.inputName ?? null}
        onClose={() => setDrawerInput(null)}
      />
    </div>
  );
}
