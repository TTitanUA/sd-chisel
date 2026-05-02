import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { useProjects, useSession, useSessionsByProject } from "@/api/sessions";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { ChatPane } from "@/components/molecules/ChatPane";
import { PromptPane } from "@/components/organisms/PromptPane";
import { SessionSettingsDrawer } from "@/components/organisms/SessionSettingsDrawer";
import { SourceImagesPane } from "@/components/organisms/SourceImagesPane";
import styles from "@/components/templates/WorkspaceLayout.module.css";

export function ProjectLanding() {
  const { projectId } = useParams();
  const sessions = useSessionsByProject(projectId);
  if (sessions.isLoading) return <div className={styles.empty}>Loading…</div>;
  const rows = sessions.data ?? [];
  if (rows.length === 0) {
    return (
      <div style={{ padding: 24, color: "var(--text-subtle)" }}>
        No sessions in this project yet. Use &quot;New session&quot; in the sidebar.
      </div>
    );
  }
  return <Navigate to={`/projects/${projectId}/sessions/${rows[0].id}`} replace />;
}

export default function WorkspaceRoute() {
  const { projectId, sessionId } = useParams();
  const session = useSession(sessionId);
  const projects = useProjects();
  const [drawerOpen, setDrawerOpen] = useState(false);

  if (!projectId || !sessionId) {
    return <div className={styles.empty}>Pick a session from the sidebar.</div>;
  }
  if (session.isLoading) return <div className={styles.empty}>Loading session…</div>;
  if (session.isError) return <div className={styles.empty}>Session not found.</div>;
  if (!session.data) return null;

  const s = session.data;
  const project = (projects.data ?? []).find((p) => p.id === projectId);

  return (
    <>
      <header className={styles.header}>
        <div className={styles.crumbs}>
          <span>{project?.name ?? projectId}</span>
          <span className={styles.sep}>/</span>
          <b>{s.name ?? "untitled"}</b>
        </div>
        <div className={styles.spacer} />
        <div className={styles.actions}>
          <Badge variant="accent">{s.session_type}</Badge>
          {s.model_name && <Badge>{s.model_name}</Badge>}
          {s.use_negative && <Badge>neg · on</Badge>}
          {s.pinned_loras.length > 0 && (
            <Badge variant="accent">{s.pinned_loras.length} pinned</Badge>
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
        <SourceImagesPane session={s} />
        <ChatPane session={s} />
        <PromptPane session={s} />
      </div>
      <SessionSettingsDrawer
        key={s.id}
        session={s}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </>
  );
}
