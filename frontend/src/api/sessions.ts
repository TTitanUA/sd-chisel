import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "./client";

export type Project = {
  id: string;
  name: string;
  session_count: number;
  created_at: number;
  updated_at: number;
};

export type PinnedLora = { lora_name: string; weight_override: number | null };

export type Session = {
  id: string;
  project_id: string;
  name: string | null;
  model_name: string | null;
  use_negative: boolean;
  pinned_loras: PinnedLora[];
  source_image_path: string | null;
  source_image_url: string | null;
  vl_summary: string | null;
  created_at: number;
  updated_at: number;
};

export type SessionCreate = {
  name?: string | null;
  model_name?: string | null;
  use_negative?: boolean;
};

export type SessionUpdate = {
  name: string | null;
  model_name: string | null;
  use_negative: boolean;
  pinned_loras: PinnedLora[];
};

export const sessionKeys = {
  projects: () => ["projects"] as const,
  sessionsByProject: (projectId: string) => ["projects", projectId, "sessions"] as const,
  session: (sessionId: string) => ["sessions", sessionId] as const,
};

export const sessionsApi = {
  listProjects: () => apiFetch<Project[]>("/api/projects"),
  createProject: (body: { name: string }) =>
    apiFetch<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  renameProject: (id: string, body: { name: string }) =>
    apiFetch<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: string) => apiFetch<void>(`/api/projects/${id}`, { method: "DELETE" }),

  listSessions: (projectId: string) => apiFetch<Session[]>(`/api/projects/${projectId}/sessions`),
  createSession: (projectId: string, body: SessionCreate) =>
    apiFetch<Session>(`/api/projects/${projectId}/sessions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getSession: (id: string) => apiFetch<Session>(`/api/sessions/${id}`),
  updateSession: (id: string, body: SessionUpdate) =>
    apiFetch<Session>(`/api/sessions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSession: (id: string) => apiFetch<void>(`/api/sessions/${id}`, { method: "DELETE" }),

  uploadSource: async (id: string, file: File): Promise<Session> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/api/sessions/${id}/source`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text()}`);
    return res.json() as Promise<Session>;
  },
  clearSource: (id: string) =>
    apiFetch<Session>(`/api/sessions/${id}/source`, { method: "DELETE" }),
};

export function useProjects() {
  return useQuery({ queryKey: sessionKeys.projects(), queryFn: sessionsApi.listProjects });
}

export function useSessionsByProject(projectId: string | undefined) {
  return useQuery({
    enabled: !!projectId,
    queryKey: projectId ? sessionKeys.sessionsByProject(projectId) : ["projects", "__noop", "sessions"],
    queryFn: () => sessionsApi.listSessions(projectId as string),
  });
}

export function useSession(sessionId: string | undefined) {
  return useQuery({
    enabled: !!sessionId,
    queryKey: sessionId ? sessionKeys.session(sessionId) : ["sessions", "__noop"],
    queryFn: () => sessionsApi.getSession(sessionId as string),
  });
}

export function useSessionInvalidation() {
  const client = useQueryClient();
  return {
    projects: () => {
      void client.invalidateQueries({ queryKey: ["projects"] });
    },
    session: (sessionId: string) => {
      void client.invalidateQueries({ queryKey: sessionKeys.session(sessionId) });
      void client.invalidateQueries({ queryKey: ["projects"] });
    },
  };
}

export function buildSourceImageSrc(session: Pick<Session, "source_image_url"> | null | undefined) {
  if (!session?.source_image_url) return null;
  return `${API_BASE}${session.source_image_url}`;
}
