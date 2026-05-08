/** Header bar — project + session crumbs, knobs toggle, Session
 *  settings. Generation lives next to the agents that produce its
 *  inputs (Single Run / Batch Run buttons in the agents-panel
 *  footer), so this header stays purely navigational. */
import { useProjects, type Session } from "@/api/sessions";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import styles from "@/components/templates/WorkspaceLayout.module.css";

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
      </div>
    </header>
  );
}
