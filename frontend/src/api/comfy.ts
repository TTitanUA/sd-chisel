import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "./client";

export type WorkflowSummary = {
  id: string;
  name: string;
  graph_hash: string;
  created_at: number;
};

export type Workflow = WorkflowSummary & {
  graph: Record<string, unknown>;
};

export type WorkflowConflict = {
  conflict: "graph_hash";
  existing: WorkflowSummary;
};

export type WorkflowUploadInput = {
  name: string;
  graph: Record<string, unknown>;
};

export type ReadinessStatus = "ready" | "needs_config" | "not_installed";

export type ReadinessCard = {
  class_type: string;
  status: ReadinessStatus;
  instance_count: number;
  display_name: string | null;
  description: string | null;
  category: string | null;
  python_module: string | null;
  pack_name: string | null;
};

export type Readiness = {
  session_id: string;
  workflow_id: string;
  ready: boolean;
  cards: ReadinessCard[];
  error: string | null;
};

export const comfyKeys = {
  workflows: () => ["comfy", "workflows"] as const,
  workflow: (id: string) => ["comfy", "workflows", id] as const,
  readiness: (sessionId: string) =>
    ["comfy", "sessions", sessionId, "readiness"] as const,
};

export const comfyApi = {
  listWorkflows: () =>
    apiFetch<{ workflows: WorkflowSummary[] }>("/api/comfy/workflows").then(
      (r) => r.workflows,
    ),
  getWorkflow: (id: string) =>
    apiFetch<Workflow>(`/api/comfy/workflows/${encodeURIComponent(id)}`),
  createWorkflow: (
    body: WorkflowUploadInput,
    onConflict: "error" | "replace" | "rename" = "error",
  ) =>
    apiFetch<Workflow>(
      `/api/comfy/workflows?on_conflict=${onConflict}`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  deleteWorkflow: (id: string) =>
    apiFetch<void>(`/api/comfy/workflows/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  getReadiness: (sessionId: string) =>
    apiFetch<Readiness>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/readiness`,
    ),
};

/** Parse a 409 conflict body returned from createWorkflow. */
export function parseWorkflowConflict(error: unknown): WorkflowConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  try {
    const body = JSON.parse(error.body) as WorkflowConflict;
    if (body && body.conflict === "graph_hash" && body.existing) return body;
  } catch {
    return null;
  }
  return null;
}

export function useWorkflows() {
  return useQuery({
    queryKey: comfyKeys.workflows(),
    queryFn: comfyApi.listWorkflows,
  });
}

export function useWorkflowsInvalidation() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: comfyKeys.workflows() });
  };
}

export function useReadiness(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: sessionId ? comfyKeys.readiness(sessionId) : ["comfy", "readiness", "unset"],
    queryFn: () => comfyApi.getReadiness(sessionId as string),
    enabled: !!sessionId,
  });
}

export function useRefreshReadiness(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => comfyApi.getReadiness(sessionId as string),
    onSuccess: () => {
      if (sessionId) {
        void client.invalidateQueries({ queryKey: comfyKeys.readiness(sessionId) });
      }
    },
  });
}
