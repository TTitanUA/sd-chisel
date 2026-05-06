import { useState } from "react";
import { useReadiness } from "@/api/comfy";
import type { Session } from "@/api/sessions";
import { SessionSettingsDrawer } from "@/components/organisms/SessionSettingsDrawer";
import workspaceStyles from "@/components/templates/WorkspaceLayout.module.css";
import { ComfyReadinessGate } from "@/features/comfy/readiness/ComfyReadinessGate";
import { SlotMapDrawer } from "@/features/comfy/slot-map/SlotMapDrawer";
import { ChatColumn } from "./ChatColumn";
import { ComfyHeader } from "./ComfyHeader";
import styles from "./ComfyWorkspace.module.css";
import { GalleryColumn } from "./GalleryColumn";
import { InspectorRail } from "./inspector/InspectorRail";

/** Comfy workspace shell.
 *
 * - Pre-readiness: a one-time gate (ComfyReadinessGate) blocks until
 *   every node class is catalogued / installed. No step machine.
 * - Post-readiness: a 3-column layout — chat + payload viewer | gallery
 *   | tabbed inspector (Slots / Bindings / Frozen / Sources / Nodes).
 *   The slot-map editor opens as a right drawer from the Slots tab.
 *
 * Phase 3 (Live PR) replaces:
 *   - the empty gallery with live `comfy_jobs` cards + a running-job
 *     progress card,
 *   - the Generate button with a Brief drawer + SSE progress,
 *   - the Bindings/Frozen tabs with live session-scoped state. */
export function ComfyWorkspace({
  session,
  projectId,
}: {
  session: Session;
  projectId: string;
}) {
  const readiness = useReadiness(session.id);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [slotMapOpen, setSlotMapOpen] = useState(false);

  const isReady = readiness.data?.ready === true;

  return (
    <>
      <ComfyHeader
        session={session}
        projectId={projectId}
        onOpenSettings={() => setDrawerOpen(true)}
        generateDisabled
        generateTitle="Generate flow lands in Phase 3 (Live PR)."
      />
      {isReady ? (
        <div className={styles.shell}>
          <ChatColumn session={session} />
          <GalleryColumn />
          <InspectorRail
            session={session}
            onEditSlots={() => setSlotMapOpen(true)}
          />
        </div>
      ) : (
        <div className={workspaceStyles.body}>
          <ComfyReadinessGate sessionId={session.id} />
        </div>
      )}
      <SlotMapDrawer
        sessionId={session.id}
        open={slotMapOpen}
        onOpenChange={setSlotMapOpen}
      />
      <SessionSettingsDrawer
        key={session.id}
        session={session}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </>
  );
}
