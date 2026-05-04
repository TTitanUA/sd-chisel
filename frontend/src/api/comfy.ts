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

// --- catalog (Library → Comfy Nodes) -----------------------------------

export type Pack = {
  name: string;
  display_name: string;
  description: string | null;
  version: string | null;
  repo_url: string | null;
  publisher_id: string | null;
  dir_path: string | null;
  node_count: number;
  imported_at: number;
};

export type NodeListItem = {
  class_type: string;
  pack_name: string;
  display_name: string;
  category: string | null;
  description_md: string;
  has_override: boolean;
  requires_semantic_config: boolean;
  imported_at: number;
};

export type PackDetail = Omit<Pack, "node_count"> & {
  readme_md: string | null;
  nodes: NodeListItem[];
};

export type NodeInputSemantic = {
  name: string;
  role_hint: string | null;
  notes: string | null;
};

export type Node = {
  class_type: string;
  pack_name: string;
  display_name: string;
  category: string | null;
  description_md: string;
  inputs_raw: Record<string, unknown> | unknown[];
  outputs_raw: unknown[];
  inputs_semantic: NodeInputSemantic[];
  requires_semantic_config: boolean;
  has_override: boolean;
  override_updated_at: number | null;
  imported_at: number;
  last_seen_in_object_info_at: number;
};

export type NodeUpdateBody = {
  description_md?: string | null;
  inputs_semantic?: NodeInputSemantic[] | null;
  category?: string | null;
};

/** Closed enum mirrored from docs/comfy-workflow-plan.md. */
export const ROLE_HINTS = [
  "positive_prompt",
  "negative_prompt",
  "seed",
  "steps",
  "cfg",
  "sampler",
  "scheduler",
  "denoise",
  "width",
  "height",
  "main_image",
  "mask_image",
  "lora_name",
  "lora_weight",
  "lora_chain_anchor",
  "checkpoint_name",
  "vae_name",
  "clip_skip",
] as const;

export type RoleHint = (typeof ROLE_HINTS)[number];

export const comfyKeys = {
  workflows: () => ["comfy", "workflows"] as const,
  workflow: (id: string) => ["comfy", "workflows", id] as const,
  readiness: (sessionId: string) =>
    ["comfy", "sessions", sessionId, "readiness"] as const,
  packs: () => ["comfy", "packs"] as const,
  pack: (name: string) => ["comfy", "packs", name] as const,
  nodes: (q?: string, pack?: string, hasDescription?: boolean) =>
    ["comfy", "nodes", { q: q ?? "", pack: pack ?? "", hasDescription: hasDescription ?? null }] as const,
  node: (classType: string) => ["comfy", "nodes", classType] as const,
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
  listPacks: () =>
    apiFetch<{ packs: Pack[] }>("/api/comfy/packs").then((r) => r.packs),
  getPack: (name: string) =>
    apiFetch<PackDetail>(`/api/comfy/packs/${encodeURIComponent(name)}`),
  listNodes: (params: { q?: string; pack?: string; hasDescription?: boolean | null } = {}) => {
    const qs = new URLSearchParams();
    if (params.q) qs.set("q", params.q);
    if (params.pack) qs.set("pack", params.pack);
    if (params.hasDescription === true) qs.set("has_description", "true");
    if (params.hasDescription === false) qs.set("has_description", "false");
    const suffix = qs.toString();
    return apiFetch<{ nodes: NodeListItem[] }>(
      `/api/comfy/nodes${suffix ? "?" + suffix : ""}`,
    ).then((r) => r.nodes);
  },
  getNode: (classType: string) =>
    apiFetch<Node>(`/api/comfy/nodes/${encodeURIComponent(classType)}`),
  updateNode: (classType: string, body: NodeUpdateBody) =>
    apiFetch<Node>(`/api/comfy/nodes/${encodeURIComponent(classType)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
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

export function usePacks() {
  return useQuery({
    queryKey: comfyKeys.packs(),
    queryFn: comfyApi.listPacks,
  });
}

export function usePack(name: string | null | undefined) {
  return useQuery({
    queryKey: name ? comfyKeys.pack(name) : ["comfy", "packs", "unset"],
    queryFn: () => comfyApi.getPack(name as string),
    enabled: !!name,
  });
}

export function useNodes(params: {
  q?: string;
  pack?: string;
  hasDescription?: boolean | null;
} = {}) {
  return useQuery({
    queryKey: comfyKeys.nodes(params.q, params.pack, params.hasDescription ?? undefined),
    queryFn: () => comfyApi.listNodes(params),
  });
}

export function useNode(classType: string | null | undefined) {
  return useQuery({
    queryKey: classType ? comfyKeys.node(classType) : ["comfy", "nodes", "unset"],
    queryFn: () => comfyApi.getNode(classType as string),
    enabled: !!classType,
  });
}

export function useUpdateNode(classType: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: NodeUpdateBody) =>
      comfyApi.updateNode(classType as string, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: comfyKeys.nodes() });
      if (classType) {
        void client.invalidateQueries({ queryKey: comfyKeys.node(classType) });
      }
    },
  });
}

export function useCatalogInvalidation() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["comfy", "packs"] });
    void client.invalidateQueries({ queryKey: ["comfy", "nodes"] });
  };
}
