/** Header bar — project + session crumbs + Session settings + Generate
 *  workflow button. Uses ComfyProvider for the workflow run state and
 *  validation message that surfaces under the button when a slot is
 *  unbound or empty. */
import { useProjects, type Session } from "@/api/sessions";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import styles from "@/components/templates/WorkspaceLayout.module.css";
import { useComfy } from "../state/useComfy";

export function ComfyHeader({
  session,
  projectId,
  onOpenSettings,
  knobsOpen,
  onToggleKnobs,
}: {
  session: Session;
  projectId: string;
  onOpenSettings: () => void;
  knobsOpen: boolean;
  onToggleKnobs: () => void;
}) {
  const { runWorkflow, isRunningWorkflow, workflowGenerateError } = useComfy();
  const projects = useProjects();
  const project = (projects.data ?? []).find((p) => p.id === projectId);

  return (
    <header className={styles.header}>
      <div className={styles.crumbs}>
        <span>{project?.name ?? projectId}</span>
        <span className={styles.sep}>/</span>
        <b>{session.name ?? "untitled"}</b>
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
        <Button
          size="sm"
          icon={<Icon name="Settings" size={12} />}
          onClick={onOpenSettings}
        >
          Session settings
        </Button>
        <div style={{ display: "flex", flexDirection: "column", gap: 2, alignItems: "flex-end" }}>
          <Button
            size="sm"
            variant="primary"
            icon={<Icon name="Sparkles" size={12} />}
            onClick={runWorkflow}
            disabled={isRunningWorkflow}
            title={workflowGenerateError ?? "Run the workflow with current state"}
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
