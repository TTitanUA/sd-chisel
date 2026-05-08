/** ComfyMock workspace shell — readiness gate (reused from real
 *  comfy) + variant switcher + the active variant's layout. State
 *  lives in `ComfyMockProvider`. See
 *  docs/comfy-agents-ui-mock-plan.md. */
import { useState } from "react";
import { useReadiness } from "@/api/comfy";
import type { Session } from "@/api/sessions";
import workspaceStyles from "@/components/templates/WorkspaceLayout.module.css";
import { ComfyReadinessGate } from "@/features/comfy/readiness/ComfyReadinessGate";
import { ComfyMockProvider } from "../state/ComfyMockProvider";
import { useVariant } from "../state/useVariant";
import { ComfyMockHeader } from "./ComfyMockHeader";
import { VariantDLayout } from "../variants/VariantDLayout";

export function ComfyMockWorkspace({
  session,
  projectId,
}: {
  session: Session;
  projectId: string;
}) {
  const readiness = useReadiness(session.id);
  // useVariant still tracks `?variant=` in the URL even though there's
  // only one valid value today — keeps the call site stable for when
  // we want to A/B again. The setter is unused right now.
  const [variant] = useVariant();
  const [knobsOpen, setKnobsOpen] = useState(
    () => new URL(window.location.href).searchParams.get("knobs") === "1",
  );
  const isReady = readiness.data?.ready === true;

  return (
    <ComfyMockProvider session={session}>
      <ComfyMockHeader
        projectId={projectId}
        knobsOpen={knobsOpen}
        onToggleKnobs={() => setKnobsOpen((o) => !o)}
      />
      {isReady ? (
        <VariantDLayout key={variant} knobsOpen={knobsOpen} />
      ) : (
        <div className={workspaceStyles.body}>
          <ComfyReadinessGate sessionId={session.id} />
        </div>
      )}
    </ComfyMockProvider>
  );
}
