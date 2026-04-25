import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Icon } from "@/components/atoms/Icon";
import {
  sessionsApi,
  useProjects,
  useSessionInvalidation,
  useSessionsByProject,
  type Project,
} from "@/api/sessions";
import styles from "./ProjectSidebar.module.css";

export function ProjectSidebar() {
  const { projectId, sessionId } = useParams();
  const navigate = useNavigate();
  const projects = useProjects();
  const invalidate = useSessionInvalidation();

  const targetProjectId = useMemo(() => {
    if (projectId) return projectId;
    return projects.data?.[0]?.id;
  }, [projectId, projects.data]);

  const createProject = useMutation({
    mutationFn: (name: string) => sessionsApi.createProject({ name }),
    onSuccess: (p: Project) => {
      invalidate.projects();
      navigate(`/projects/${p.id}`);
    },
  });

  const createSession = useMutation({
    mutationFn: (pid: string) =>
      sessionsApi.createSession(pid, {
        name: `untitled · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
        model_name: null,
        use_negative: true,
      }),
    onSuccess: (s) => {
      invalidate.projects();
      navigate(`/projects/${s.project_id}/sessions/${s.id}`);
    },
  });

  return (
    <aside className={styles.sidebar}>
      <div className={styles.head}>
        <span className={styles.headTitle}>Projects</span>
        <button
          type="button"
          className={styles.iconBtn}
          title="New project"
          onClick={() => {
            const name = window.prompt("Project name?");
            if (name?.trim()) createProject.mutate(name.trim());
          }}
        >
          <Icon name="Plus" />
        </button>
      </div>
      <div className={styles.scroll}>
        {(projects.data ?? []).map((p) => (
          <ProjectRow
            key={p.id}
            project={p}
            activeProjectId={projectId}
            activeSessionId={sessionId}
          />
        ))}
        {projects.data?.length === 0 && (
          <div className={styles.empty}>No projects yet. Create one to get started.</div>
        )}
        <button
          type="button"
          className={styles.sidebarNew}
          disabled={!targetProjectId || createSession.isPending}
          title={targetProjectId ? "New session in current or first project" : "Create a project first"}
          onClick={() => {
            if (targetProjectId) createSession.mutate(targetProjectId);
          }}
        >
          <Icon name="Plus" size={12} />
          New session
        </button>
      </div>
      <div className={styles.foot}>
        <span>Quarry · v0.3</span>
        <Link
          to="/settings/lmstudio"
          className={styles.footBtn}
          title="Settings"
          aria-label="Settings"
        >
          <Icon name="Settings" size={12} />
        </Link>
      </div>
    </aside>
  );
}

function ProjectRow({
  project,
  activeProjectId,
  activeSessionId,
}: {
  project: Project;
  activeProjectId: string | undefined;
  activeSessionId: string | undefined;
}) {
  const [open, setOpen] = useState(() => project.id === activeProjectId);
  const sessions = useSessionsByProject(open ? project.id : undefined);
  const navigate = useNavigate();

  return (
    <div className={styles.projGroup}>
      <button
        type="button"
        className={styles.projRow}
        data-open={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={styles.chev}>
          <Icon name="ChevronDown" size={10} />
        </span>
        <span className={styles.projName}>{project.name}</span>
        <span className={styles.projCount}>{project.session_count}</span>
      </button>
      {open && (
        <div className={styles.sessionList}>
          {(sessions.data ?? []).map((s) => {
            const isActive = s.id === activeSessionId;
            return (
              <button
                key={s.id}
                type="button"
                className={[
                  styles.sessionRow,
                  isActive ? styles.sessionRowActive : "",
                  s.source_image_path ? styles.sessionRowHasResult : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => navigate(`/projects/${project.id}/sessions/${s.id}`)}
              >
                <span className={styles.sesDot} aria-hidden />
                <span className={styles.sesName}>{s.name ?? "untitled"}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
