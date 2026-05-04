import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "./client";

export type Project = {
  id: string;
  name: string;
  session_count: number;
  hidden: boolean;
  created_at: number;
  updated_at: number;
};

export type PinnedLora = { lora_name: string; weight_override: number | null };

export type SessionType = "i2i" | "t2i" | "comfy";

export type SourceImage = {
  id: string;
  session_id: string;
  path: string;
  url: string;
  original_filename: string;
  image_number: number;
  is_main: boolean;
  analysis: string | null;
  analysis_prompt: string | null;
  created_at: number;
  updated_at: number;
};

export function imageDisplayName(image: Pick<SourceImage, "image_number">): string {
  return `Image_${image.image_number}`;
}

export type SamplingBundle = Record<string, number>;

export type Session = {
  id: string;
  project_id: string;
  name: string | null;
  session_type: SessionType;
  model_name: string | null;
  use_negative: boolean;
  pinned_loras: PinnedLora[];
  source_images: SourceImage[];
  vl_model_name: string | null;
  prompt_model_name: string | null;
  analyze_settings?: SamplingBundle | null;
  chat_settings?: SamplingBundle | null;
  summarize_settings?: SamplingBundle | null;
  generate_settings?: SamplingBundle | null;
  comfy_workflow_id?: string | null;
  hidden: boolean;
  created_at: number;
  updated_at: number;
};

export type SessionCreate = {
  session_type: SessionType;
  name?: string | null;
  model_name?: string | null;
  use_negative?: boolean;
  comfy_workflow_id?: string | null;
};

export type SessionUpdate = {
  name: string | null;
  model_name: string | null;
  use_negative: boolean;
  pinned_loras: PinnedLora[];
  vl_model_name: string | null;
  prompt_model_name: string | null;
  // Optional partial bundles. Absent fields = leave column alone; null/{} = clear all overrides.
  analyze_settings?: SamplingBundle | null;
  chat_settings?: SamplingBundle | null;
  summarize_settings?: SamplingBundle | null;
  generate_settings?: SamplingBundle | null;
};

export type Action = "analyze" | "chat" | "summarize" | "generate";
export const ACTION_SETTINGS_FIELDS: Record<Action, keyof Session> = {
  analyze: "analyze_settings",
  chat: "chat_settings",
  summarize: "summarize_settings",
  generate: "generate_settings",
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
  setProjectHidden: (id: string, hidden: boolean) =>
    apiFetch<Project>(`/api/projects/${id}/hidden`, {
      method: "PATCH",
      body: JSON.stringify({ hidden }),
    }),
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
  setSessionHidden: (id: string, hidden: boolean) =>
    apiFetch<Session>(`/api/sessions/${id}/hidden`, {
      method: "PATCH",
      body: JSON.stringify({ hidden }),
    }),
  deleteSession: (id: string) => apiFetch<void>(`/api/sessions/${id}`, { method: "DELETE" }),

  listSources: (sessionId: string) =>
    apiFetch<SourceImage[]>(`/api/sessions/${sessionId}/sources`),
  uploadSource: async (sessionId: string, file: File): Promise<SourceImage> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/sources`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error(`upload failed: ${res.status} ${await res.text()}`);
    return res.json() as Promise<SourceImage>;
  },
  deleteSource: (sessionId: string, imageId: string) =>
    apiFetch<void>(`/api/sessions/${sessionId}/sources/${imageId}`, {
      method: "DELETE",
    }),
  setMainSource: (sessionId: string, imageId: string) =>
    apiFetch<SourceImage>(
      `/api/sessions/${sessionId}/sources/${imageId}/main`,
      { method: "PATCH" },
    ),
  analyzeSource: (
    sessionId: string,
    imageId: string,
    refining_prompt: string | null,
  ) =>
    apiFetch<SourceImage>(
      `/api/sessions/${sessionId}/sources/${imageId}/analyze`,
      { method: "POST", body: JSON.stringify({ refining_prompt }) },
    ),
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

export function buildSourceImageSrc(image: Pick<SourceImage, "url"> | null | undefined) {
  if (!image?.url) return null;
  return `${API_BASE}${image.url}`;
}
