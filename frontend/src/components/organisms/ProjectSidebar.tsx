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
// Note: session creation moved to the dedicated /projects/:id/sessions/new
// route; the sidebar only navigates there.
import { useShowHidden } from "@/api/settings";
import styles from "./ProjectSidebar.module.css";

export function ProjectSidebar() {
  const { projectId, sessionId } = useParams();
  const navigate = useNavigate();
  const projects = useProjects();
  const invalidate = useSessionInvalidation();
  const [search, setSearch] = useState("");
  const showHidden = useShowHidden();

  const filteredProjects = useMemo(() => {
    const q = search.trim().toLowerCase();
    const all = (projects.data ?? []).filter((p) => showHidden || !p.hidden);
    if (!q) return all;
    return all.filter((p) => p.name.toLowerCase().includes(q));
  }, [projects.data, search, showHidden]);

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
      <label className={styles.searchWrap}>
        <Icon name="Search" size={12} className={styles.searchIcon} aria-hidden />
        <input
          className={styles.search}
          value={search}
          placeholder="Search projects…"
          onChange={(event) => setSearch(event.currentTarget.value)}
          aria-label="Search projects"
        />
      </label>
      <div className={styles.scroll}>
        {filteredProjects.map((p) => (
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
        {projects.data && projects.data.length > 0 && filteredProjects.length === 0 && (
          <div className={styles.empty}>
            {search.trim()
              ? `No projects match “${search}”.`
              : "All projects are hidden. Toggle “Show hidden items” in Settings → Privacy."}
          </div>
        )}
        <button
          type="button"
          className={styles.sidebarNew}
          disabled={!targetProjectId}
          title={targetProjectId ? "New session in current or first project" : "Create a project first"}
          onClick={() => {
            if (targetProjectId) navigate(`/projects/${targetProjectId}/sessions/new`);
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
  const showHidden = useShowHidden();
  const invalidate = useSessionInvalidation();
  const navigate = useNavigate();

  const visibleSessions = (sessions.data ?? []).filter((s) => showHidden || !s.hidden);

  const setProjectHidden = useMutation({
    mutationFn: (hidden: boolean) => sessionsApi.setProjectHidden(project.id, hidden),
    onSuccess: () => invalidate.projects(),
  });
  const setSessionHidden = useMutation({
    mutationFn: ({ id, hidden }: { id: string; hidden: boolean }) =>
      sessionsApi.setSessionHidden(id, hidden),
    onSuccess: () => invalidate.projects(),
  });

  return (
    <div className={styles.projGroup} data-hidden={project.hidden ? "true" : undefined}>
      <div className={styles.projRowWrap} data-open={open}>
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
        <button
          type="button"
          className={styles.rowAction}
          aria-label={project.hidden ? "Unhide project" : "Hide project"}
          title={project.hidden ? "Unhide project" : "Hide project"}
          onClick={(e) => {
            e.stopPropagation();
            setProjectHidden.mutate(!project.hidden);
          }}
        >
          <Icon name={project.hidden ? "Eye" : "EyeOff"} size={11} />
        </button>
      </div>
      {open && (
        <div className={styles.sessionList}>
          {visibleSessions.map((s) => {
            const isActive = s.id === activeSessionId;
            return (
              <div
                key={s.id}
                className={styles.sessionRowWrap}
                data-hidden={s.hidden ? "true" : undefined}
              >
                <button
                  type="button"
                  className={[
                    styles.sessionRow,
                    isActive ? styles.sessionRowActive : "",
                    s.source_images.length > 0 ? styles.sessionRowHasResult : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => navigate(`/projects/${project.id}/sessions/${s.id}`)}
                >
                  <span className={styles.sesDot} aria-hidden />
                  <span className={styles.sesName}>{s.name ?? "untitled"}</span>
                </button>
                <button
                  type="button"
                  className={styles.rowAction}
                  aria-label={s.hidden ? "Unhide session" : "Hide session"}
                  title={s.hidden ? "Unhide session" : "Hide session"}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSessionHidden.mutate({ id: s.id, hidden: !s.hidden });
                  }}
                >
                  <Icon name={s.hidden ? "Eye" : "EyeOff"} size={11} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
