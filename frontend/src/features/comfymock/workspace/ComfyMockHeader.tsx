/** Header bar — project + workflow + Generate workflow button. The
 *  generate validation message surfaces under the button when a slot
 *  is unbound or empty. See docs/comfy-agents-ui-mock-plan.md. */
import { useProjects } from "@/api/sessions";
import { Button } from "@/components/atoms/Button";
import styles from "@/components/templates/WorkspaceLayout.module.css";
import { useComfyMock } from "../state/useComfyMock";

export function ComfyMockHeader({
  projectId,
  knobsOpen,
  onToggleKnobs,
}: {
  projectId: string;
  knobsOpen: boolean;
  onToggleKnobs: () => void;
}) {
  const { session, runWorkflow, isRunningWorkflow, workflowGenerateError } =
    useComfyMock();
  const projects = useProjects();
  const project = (projects.data ?? []).find((p) => p.id === projectId);

  return (
    <header className={styles.header}>
      <div className={styles.crumbs}>
        <span>{project?.name ?? projectId}</span>
        <span className={styles.sep}>/</span>
        <b>{session.name ?? "untitled"}</b>
        <span className={styles.sep}>·</span>
        <span style={{ color: "var(--accent)", fontSize: 11 }}>
          ComfyMock
        </span>
      </div>
      <div className={styles.spacer} />
      <div className={styles.actions}>
        <Button
          size="sm"
          onClick={onToggleKnobs}
          variant={knobsOpen ? "primary" : "secondary"}
        >
          knobs
        </Button>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-end" }}>
          <Button
            size="sm"
            variant="primary"
            onClick={runWorkflow}
            disabled={isRunningWorkflow}
            title={
              workflowGenerateError ?? "Run the workflow with current state"
            }
          >
            {isRunningWorkflow ? "Generating…" : "Generate workflow"}
          </Button>
          {workflowGenerateError && (
            <span style={{ fontSize: 10, color: "var(--danger)", maxWidth: 320, textAlign: "right" }}>
              {workflowGenerateError}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}
