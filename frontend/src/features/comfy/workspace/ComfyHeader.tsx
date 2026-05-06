import { useProjects, type Session } from "@/api/sessions";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import styles from "@/components/templates/WorkspaceLayout.module.css";

export function ComfyHeader({
  session,
  projectId,
  onOpenSettings,
  onGenerate,
  generateDisabled,
  generateTitle,
}: {
  session: Session;
  projectId: string;
  onOpenSettings: () => void;
  onGenerate?: () => void;
  generateDisabled?: boolean;
  generateTitle?: string;
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
        {session.pinned_loras.length > 0 && (
          <Badge variant="accent">{session.pinned_loras.length} pinned</Badge>
        )}
        <Button
          size="sm"
          variant="primary"
          icon={<Icon name="Sparkles" size={12} />}
          onClick={onGenerate}
          disabled={generateDisabled}
          title={generateTitle ?? "Compose a brief and queue a generation"}
        >
          Generate
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
