import { useState } from "react";
import { useProjects, type Session } from "@/api/sessions";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { ChatPane } from "@/components/molecules/ChatPane";
import { PromptPane } from "@/components/organisms/PromptPane";
import { SessionSettingsDrawer } from "@/components/organisms/SessionSettingsDrawer";
import { SourceImagesPane } from "@/components/organisms/SourceImagesPane";
import styles from "@/components/templates/WorkspaceLayout.module.css";

export function T2iWorkspace({
  session,
  projectId,
}: {
  session: Session;
  projectId: string;
}) {
  const projects = useProjects();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const project = (projects.data ?? []).find((p) => p.id === projectId);

  return (
    <>
      <header className={styles.header}>
        <div className={styles.crumbs}>
          <span>{project?.name ?? projectId}</span>
          <span className={styles.sep}>/</span>
          <b>{session.name ?? "untitled"}</b>
        </div>
        <div className={styles.spacer} />
        <div className={styles.actions}>
          <Badge variant="accent">{session.session_type}</Badge>
          {session.model_name && <Badge>{session.model_name}</Badge>}
          {session.use_negative && <Badge>neg · on</Badge>}
          {session.pinned_loras.length > 0 && (
            <Badge variant="accent">{session.pinned_loras.length} pinned</Badge>
          )}
          <Button
            size="sm"
            icon={<Icon name="Settings" size={12} />}
            onClick={() => setDrawerOpen(true)}
          >
            Session settings
          </Button>
        </div>
      </header>
      <div className={styles.grid}>
        <SourceImagesPane session={session} />
        <ChatPane session={session} />
        <PromptPane session={session} />
      </div>
      <SessionSettingsDrawer
        key={session.id}
        session={session}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </>
  );
}
