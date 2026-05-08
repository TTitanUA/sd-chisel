import { useState } from "react";
import { useReadiness } from "@/api/comfy";
import type { Session } from "@/api/sessions";
import { SessionSettingsDrawer } from "@/components/organisms/SessionSettingsDrawer";
import workspaceStyles from "@/components/templates/WorkspaceLayout.module.css";
import { ComfyReadinessGate } from "@/features/comfy/readiness/ComfyReadinessGate";
import { ComfyProvider } from "../state/ComfyProvider";
import { ComfyHeader } from "./ComfyHeader";
import { ComfyWorkspaceLayout } from "./ComfyWorkspaceLayout";

/** Comfy workspace shell.
 *
 * Pre-readiness: a one-time gate (ComfyReadinessGate) blocks until
 * every node class is catalogued / installed.
 *
 * Post-readiness: ComfyWorkspaceLayout — IDE-like layout with a left
 * tab bar (Agents / Inputs / Sources / Nodes / Chat), centre toggle
 * between agent editor and the slot-mapping tree, and a collapsible
 * gallery footer. Per-agent /run, workflow Generate, chat replies and
 * job history are emulated client-side until the matching backend
 * endpoints land — see docs/comfy-agents-ui-mock-plan.md. */
export function ComfyWorkspace({
  session,
  projectId,
}: {
  session: Session;
  projectId: string;
}) {
  const readiness = useReadiness(session.id);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [knobsOpen, setKnobsOpen] = useState(
    () => new URL(window.location.href).searchParams.get("knobs") === "1",
  );

  const isReady = readiness.data?.ready === true;

  return (
    <ComfyProvider session={session}>
      <ComfyHeader
        session={session}
        projectId={projectId}
        onOpenSettings={() => setDrawerOpen(true)}
        knobsOpen={knobsOpen}
        onToggleKnobs={() => setKnobsOpen((o) => !o)}
      />
      {isReady ? (
        <ComfyWorkspaceLayout knobsOpen={knobsOpen} />
      ) : (
        <div className={workspaceStyles.body}>
          <ComfyReadinessGate sessionId={session.id} />
        </div>
      )}
      <SessionSettingsDrawer
        key={session.id}
        session={session}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </ComfyProvider>
  );
}
