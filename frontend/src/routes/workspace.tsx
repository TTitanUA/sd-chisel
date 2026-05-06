import { Navigate, useParams } from "react-router-dom";
import { useSession, useSessionsByProject } from "@/api/sessions";
import { ComfyWorkspace } from "@/features/comfy";
import { I2iWorkspace } from "@/features/i2i";
import { T2iWorkspace } from "@/features/t2i";
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

  if (!projectId || !sessionId) {
    return <div className={styles.empty}>Pick a session from the sidebar.</div>;
  }
  if (session.isLoading) return <div className={styles.empty}>Loading session…</div>;
  if (session.isError) return <div className={styles.empty}>Session not found.</div>;
  if (!session.data) return null;

  const s = session.data;
  switch (s.session_type) {
    case "i2i":
      return <I2iWorkspace session={s} projectId={projectId} />;
    case "t2i":
      return <T2iWorkspace session={s} projectId={projectId} />;
    case "comfy":
      return <ComfyWorkspace session={s} projectId={projectId} />;
  }
}
