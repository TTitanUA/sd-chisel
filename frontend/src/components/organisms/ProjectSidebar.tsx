import { useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
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

  const createProject = useMutation({
    mutationFn: (name: string) => sessionsApi.createProject({ name }),
    onSuccess: (p: Project) => {
      invalidate.projects();
      navigate(`/projects/${p.id}`);
    },
  });

  return (
    <aside className={styles.sidebar}>
      <div className={styles.head}>
        <span>Projects</span>
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
        <div className={styles.sectionDivider} />
        <nav className={styles.libraryNav}>
          <NavLink
            to="/library/families"
            className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}
          >
            Library — Families
          </NavLink>
          <NavLink
            to="/library/models"
            className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}
          >
            Library — Models
          </NavLink>
          <NavLink
            to="/library/loras"
            className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}
          >
            Library — LoRAs
          </NavLink>
        </nav>
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
  const invalidate = useSessionInvalidation();

  const createSession = useMutation({
    mutationFn: () =>
      sessionsApi.createSession(project.id, {
        name: `untitled · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
        model_name: null,
        use_negative: true,
      }),
    onSuccess: (s) => {
      invalidate.projects();
      navigate(`/projects/${project.id}/sessions/${s.id}`);
    },
  });

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
                className={`${styles.sessionRow} ${isActive ? styles.active : ""}`}
                onClick={() => navigate(`/projects/${project.id}/sessions/${s.id}`)}
              >
                {s.name ?? "untitled"}
              </button>
            );
          })}
          <Button
            variant="secondary"
            size="sm"
            icon={<Icon name="Plus" size={10} />}
            onClick={() => createSession.mutate()}
          >
            New session
          </Button>
        </div>
      )}
    </div>
  );
}
