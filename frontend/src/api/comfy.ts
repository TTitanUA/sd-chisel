import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, ApiError, apiFetch } from "./client";

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

// --- per-node import wizard (SSE) ---------------------------------------

export const IMPORT_STAGES = [
  "locate_pack",
  "fetch_schema",
  "enrich_llm",
  "persist",
] as const;
export type ImportStage = (typeof IMPORT_STAGES)[number];

export const IMPORT_STAGE_LABEL: Record<ImportStage, string> = {
  locate_pack: "Locate pack",
  fetch_schema: "Fetch schema",
  enrich_llm: "Generate description",
  persist: "Save to catalog",
};

export type ImportEvent =
  | { type: "stage_started"; stage: ImportStage | "internal" }
  | { type: "stage_succeeded"; stage: ImportStage; data: Record<string, unknown> }
  | { type: "stage_failed"; stage: ImportStage | "internal"; error: string }
  | { type: "done"; class_type: string; node: Node };

/** Stream the SSE events from a per-node import. The promise resolves
 * once the stream ends; events are reported through the callback. */
export async function runImport(
  classType: string,
  onEvent: (event: ImportEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/comfy/nodes/${encodeURIComponent(classType)}/import`,
    { method: "POST", signal },
  );
  if (!res.ok || !res.body) {
    const body = res.body ? await res.text() : "";
    throw new ApiError(res.status, body || "import endpoint failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE frames end with a blank line.
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of frame.split("\n")) {
          const trimmed = line.replace(/^data:\s?/, "");
          if (!trimmed || trimmed === line) continue;
          try {
            onEvent(JSON.parse(trimmed) as ImportEvent);
          } catch {
            // Skip malformed lines; the server-side schema is strict.
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}


// --- Phase 2.5: workflow-declared, typed, labelled slots ----------------
//
// The Phase 2 model exposed three fixed slots. Phase 2.5 replaces it
// with a per-workflow list of labelled slots, each carrying a kind
// (text / image / number / enum / …) and a binding (who fills the
// value at generation time). See docs/comfy-workflow-plan.md
// "Phase 2.5".

export const SLOT_KINDS = [
  "text",
  "multiline_text",
  "image",
  "image_alpha",
  "number_int",
  "number_float",
  "boolean",
  "enum",
  "lora_name",
  "checkpoint_name",
] as const;
export type SlotKind = (typeof SLOT_KINDS)[number];

export const SLOT_KIND_LABEL: Record<SlotKind, string> = {
  text: "Text",
  multiline_text: "Multiline text",
  image: "Image",
  image_alpha: "Image (alpha)",
  number_int: "Integer",
  number_float: "Float",
  boolean: "Boolean",
  enum: "Enum",
  lora_name: "LoRA",
  checkpoint_name: "Checkpoint",
};

export const SLOT_BINDINGS = [
  "llm",
  "frozen",
  "user_image",
  "library_loras",
] as const;
export type SlotBinding = (typeof SLOT_BINDINGS)[number];

export const SLOT_BINDING_LABEL: Record<SlotBinding, string> = {
  llm: "Composed by LLM",
  frozen: "Fixed value",
  user_image: "Session image",
  library_loras: "LoRA library",
};

/** Mirror of backend ALLOWED_BINDINGS. Used to populate the binding
 *  dropdown per slot row.
 *
 *  `lora_name` allows `llm` because an agent that's been given a
 *  LoRAs input slot can pick a name from that constrained pool — same
 *  shape as picking an enum value. The agent-side editor still gates
 *  the lora_name kind on actually having such an input slot.
 *  `checkpoint_name` stays frozen-only: checkpoints are global model
 *  files, not something an agent picks at run time. */
export const ALLOWED_BINDINGS: Record<SlotKind, SlotBinding[]> = {
  text:            ["llm", "frozen"],
  multiline_text:  ["llm", "frozen"],
  image:           ["user_image", "frozen"],
  image_alpha:     ["user_image", "frozen"],
  number_int:      ["llm", "frozen"],
  number_float:    ["llm", "frozen"],
  boolean:         ["llm", "frozen"],
  enum:            ["llm", "frozen"],
  lora_name:       ["llm", "frozen"],
  checkpoint_name: ["frozen"],
};

export const DEFAULT_BINDING: Record<SlotKind, SlotBinding> = {
  text:            "llm",
  multiline_text:  "llm",
  image:           "user_image",
  image_alpha:     "user_image",
  number_int:      "frozen",
  number_float:    "frozen",
  boolean:         "frozen",
  enum:            "frozen",
  lora_name:       "frozen",
  checkpoint_name: "frozen",
};

export type SlotOrigin = { node_id: string; input_name: string };

export type SlotDefinition = {
  label: string;
  group: string | null;
  ordinal: number | null;
  description: string | null;
  kind: SlotKind;
  origin: SlotOrigin;
  binding: SlotBinding;
  metadata: Record<string, unknown>;
};

export type SlotMapV2 = {
  version: 2;
  slots: SlotDefinition[];
};

export type CandidateInput = {
  node_id: string;
  input_name: string;
  node_class_type: string;
  node_display_name: string | null;
  node_title: string | null;
  node_in_catalog: boolean;
  current_value: unknown;
  kind: SlotKind;
  metadata: Record<string, unknown>;
};

export type CandidateBuckets = Record<SlotKind, CandidateInput[]>;

export type InferredMode = "i2i" | "t2i";

export type SlotMapResponse = {
  session_id: string;
  workflow_id: string;
  slot_map: SlotMapV2;
  candidates: CandidateBuckets;
  inferred_mode: InferredMode;
};

// Phase 3 only drives image inputs / outputs through these node
// classes. Mirrors backend's IMAGE_LOADER_CLASSES / IMAGE_SAVER_CLASSES
// so the UI can filter pickers + show a "LoadImage only" hint without
// a round-trip.
export const IMAGE_LOADER_CLASSES: ReadonlySet<string> = new Set([
  "LoadImage",
]);
export const IMAGE_SAVER_CLASSES: ReadonlySet<string> = new Set([
  "SaveImage",
]);

// --- Output slot map (PR-2 prep, symmetric to slot map) ----------------

export type OutputKind = "image";

export type OutputSlotDefinition = {
  label: string;
  node_id: string;
  kind: OutputKind;
};

export type OutputSlotMapV1 = {
  version: 1;
  outputs: OutputSlotDefinition[];
};

export type OutputCandidate = {
  node_id: string;
  node_class_type: string;
  node_display_name: string | null;
  node_title: string | null;
  node_in_catalog: boolean;
  kind: OutputKind;
  filename_prefix: string | null;
};

export type OutputSlotMapResponse = {
  session_id: string;
  workflow_id: string;
  output_slot_map: OutputSlotMapV1;
  candidates: OutputCandidate[];
};

export const comfyKeys = {
  workflows: () => ["comfy", "workflows"] as const,
  workflow: (id: string) => ["comfy", "workflows", id] as const,
  readiness: (sessionId: string) =>
    ["comfy", "sessions", sessionId, "readiness"] as const,
  slotMap: (sessionId: string) =>
    ["comfy", "sessions", sessionId, "slot_map"] as const,
  outputSlotMap: (sessionId: string) =>
    ["comfy", "sessions", sessionId, "output_slot_map"] as const,
  agents: (sessionId: string) =>
    ["comfy", "sessions", sessionId, "agents"] as const,
  agent: (sessionId: string, agentId: string) =>
    ["comfy", "sessions", sessionId, "agents", agentId] as const,
  packs: () => ["comfy", "packs"] as const,
  pack: (name: string) => ["comfy", "packs", name] as const,
  nodes: (q?: string, pack?: string, hasDescription?: boolean) =>
    ["comfy", "nodes", { q: q ?? "", pack: pack ?? "", hasDescription: hasDescription ?? null }] as const,
  node: (classType: string) => ["comfy", "nodes", classType] as const,
};

// --- Comfy agents (per-session, user-programmable) ----------------------

export type SourceScope = "all" | "selected" | "none";
export type SlotOriginKind = "preset" | "custom" | "auto";
export type PresetOutputName = "positive" | "negative";

export type AgentSlotBinding = { workflow_slot_label: string };

export type AgentOutputSlot = {
  id: string;
  origin: SlotOriginKind;
  preset: PresetOutputName | null;
  kind: SlotKind | null;
  label: string;
  description: string | null;
  last_value: unknown;
  bound_to: AgentSlotBinding | null;
};

export type Agent = {
  id: string;
  session_id: string;
  position: number;
  name: string;
  prompt: string;
  model_name: string | null;
  model_params: Record<string, unknown> | null;
  source_scope: SourceScope;
  source_ids: string[] | null;
  loras_enabled: boolean;
  output_slots: AgentOutputSlot[];
  last_run_at: number | null;
  created_at: number;
  updated_at: number;
};

export type AgentCreateBody = {
  name: string;
  prompt?: string;
  model_name?: string | null;
  model_params?: Record<string, unknown> | null;
  source_scope?: SourceScope;
  source_ids?: string[] | null;
  loras_enabled?: boolean;
  output_slots?: AgentOutputSlot[];
};

export type AgentUpdateBody = Partial<{
  name: string;
  prompt: string;
  model_name: string | null;
  model_params: Record<string, unknown> | null;
  source_scope: SourceScope;
  source_ids: string[] | null;
  loras_enabled: boolean;
  output_slots: AgentOutputSlot[];
  position: number;
}>;

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
  getSlotMap: (sessionId: string) =>
    apiFetch<SlotMapResponse>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/slot_map`,
    ),
  putSlotMap: (sessionId: string, slots: SlotDefinition[]) =>
    apiFetch<SlotMapResponse>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/slot_map`,
      { method: "PUT", body: JSON.stringify({ slots }) },
    ),
  getOutputSlotMap: (sessionId: string) =>
    apiFetch<OutputSlotMapResponse>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/output_slot_map`,
    ),
  putOutputSlotMap: (sessionId: string, outputs: OutputSlotDefinition[]) =>
    apiFetch<OutputSlotMapResponse>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/output_slot_map`,
      { method: "PUT", body: JSON.stringify({ outputs }) },
    ),
  // --- agents -----------------------------------------------------------
  listAgents: (sessionId: string) =>
    apiFetch<{ agents: Agent[] }>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/agents`,
    ).then((r) => r.agents),
  createAgent: (sessionId: string, body: AgentCreateBody) =>
    apiFetch<Agent>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/agents`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  updateAgent: (sessionId: string, agentId: string, body: AgentUpdateBody) =>
    apiFetch<Agent>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  deleteAgent: (sessionId: string, agentId: string) =>
    apiFetch<void>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}`,
      { method: "DELETE" },
    ),
  seedDefaultAgent: (sessionId: string) =>
    apiFetch<{ agent: Agent }>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/agents/seed_default`,
      { method: "POST" },
    ).then((r) => r.agent),
  runAgent: (
    sessionId: string,
    agentId: string,
    body?: { source_image_overrides?: Record<string, string | null> },
  ) =>
    apiFetch<Agent>(
      `/api/comfy/sessions/${encodeURIComponent(sessionId)}/agents/${encodeURIComponent(agentId)}/run`,
      { method: "POST", body: JSON.stringify(body ?? {}) },
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

export function useSlotMap(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: sessionId ? comfyKeys.slotMap(sessionId) : ["comfy", "slot_map", "unset"],
    queryFn: () => comfyApi.getSlotMap(sessionId as string),
    enabled: !!sessionId,
  });
}

export function useSaveSlotMap(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (slots: SlotDefinition[]) =>
      comfyApi.putSlotMap(sessionId as string, slots),
    onSuccess: (data) => {
      if (sessionId) {
        client.setQueryData(comfyKeys.slotMap(sessionId), data);
      }
    },
  });
}

export function useOutputSlotMap(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: sessionId
      ? comfyKeys.outputSlotMap(sessionId)
      : ["comfy", "output_slot_map", "unset"],
    queryFn: () => comfyApi.getOutputSlotMap(sessionId as string),
    enabled: !!sessionId,
  });
}

export function useSaveOutputSlotMap(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (outputs: OutputSlotDefinition[]) =>
      comfyApi.putOutputSlotMap(sessionId as string, outputs),
    onSuccess: (data) => {
      if (sessionId) {
        client.setQueryData(comfyKeys.outputSlotMap(sessionId), data);
      }
    },
  });
}

// --- Agents hooks --------------------------------------------------------

export function useAgents(sessionId: string | null | undefined) {
  return useQuery({
    queryKey: sessionId ? comfyKeys.agents(sessionId) : ["comfy", "agents", "unset"],
    queryFn: () => comfyApi.listAgents(sessionId as string),
    enabled: !!sessionId,
  });
}

export function useCreateAgent(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AgentCreateBody) =>
      comfyApi.createAgent(sessionId as string, body),
    onSuccess: () => {
      if (sessionId) {
        void client.invalidateQueries({ queryKey: comfyKeys.agents(sessionId) });
      }
    },
  });
}

export function useUpdateAgent(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ agentId, body }: { agentId: string; body: AgentUpdateBody }) =>
      comfyApi.updateAgent(sessionId as string, agentId, body),
    onSuccess: () => {
      if (sessionId) {
        void client.invalidateQueries({ queryKey: comfyKeys.agents(sessionId) });
      }
    },
  });
}

export function useDeleteAgent(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      comfyApi.deleteAgent(sessionId as string, agentId),
    onSuccess: () => {
      if (sessionId) {
        void client.invalidateQueries({ queryKey: comfyKeys.agents(sessionId) });
      }
    },
  });
}

export function useSeedDefaultAgent(sessionId: string | null | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => comfyApi.seedDefaultAgent(sessionId as string),
    onSuccess: () => {
      if (sessionId) {
        void client.invalidateQueries({ queryKey: comfyKeys.agents(sessionId) });
      }
    },
  });
}
