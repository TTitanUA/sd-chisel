import { useState } from "react";
import type { Session } from "@/api/sessions";
import { BindingsTab } from "./BindingsTab";
import { FrozenTab } from "./FrozenTab";
import { NodesTab } from "./NodesTab";
import { SlotsTab } from "./SlotsTab";
import { SourcesTab } from "./SourcesTab";
import styles from "./InspectorRail.module.css";

export type InspectorTab = "slots" | "bindings" | "frozen" | "sources" | "nodes";

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "slots", label: "Slots" },
  { id: "bindings", label: "Bindings" },
  { id: "frozen", label: "Frozen" },
  { id: "sources", label: "Sources" },
  { id: "nodes", label: "Nodes" },
];

export function InspectorRail({
  session,
  onEditSlots,
}: {
  session: Session;
  onEditSlots: () => void;
}) {
  const [active, setActive] = useState<InspectorTab>("slots");

  return (
    <aside className={styles.rail} aria-label="Inspector">
      <nav className={styles.tabs} role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active === tab.id}
            data-active={active === tab.id || undefined}
            className={styles.tab}
            onClick={() => setActive(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <div className={styles.body} role="tabpanel">
        {active === "slots" && (
          <SlotsTab session={session} onEditSlots={onEditSlots} />
        )}
        {active === "bindings" && <BindingsTab session={session} />}
        {active === "frozen" && <FrozenTab session={session} />}
        {active === "sources" && <SourcesTab session={session} />}
        {active === "nodes" && <NodesTab session={session} />}
      </div>
    </aside>
  );
}
