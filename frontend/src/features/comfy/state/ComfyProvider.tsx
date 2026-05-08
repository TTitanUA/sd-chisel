/**
 * ComfyMock state provider — reconciles real API hooks (workflow,
 * slot map, agents, sources) with browser-only state (chat, jobs,
 * selected agent, running flags) and exposes the action set the
 * variants render against.
 *
 * Per-agent run + workflow-level Generate are emulated client-side
 * (10 s LLM, 1.5 s queue) and PATCH the agent's `last_value`s back
 * to the backend so they persist across reload exactly the way real
 * runs will.
 *
 * See docs/comfy-agents-ui-mock-plan.md.
 */
import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  comfyApi,
  comfyKeys,
  useAgents,
  useSlotMap,
  type Agent,
  type SlotMapResponse,
} from "@/api/comfy";
import { ApiError } from "@/api/client";
import type { Session } from "@/api/sessions";
import { emulateChatReply } from "../mocks/chat-emulator";
import { renderFakeResult } from "../mocks/fake-result";
import {
  deleteSnapshot as removeSnapshot,
  loadSnapshots,
  saveSnapshot,
  type JobSnapshot,
} from "../mocks/job-snapshots";
import {
  loadSourceSlots,
  saveSourceSlots,
  type SourceSlot,
} from "./source-slots";

const WORKFLOW_QUEUE_DELAY_MS = 1_500;

/** Pull the FastAPI ``detail`` field out of an ApiError body. The
 *  comfy router uses HTTPException with a string detail for every
 *  precondition failure (no LMStudio URL, no model, no composable
 *  slots, …). Returns null if the body isn't a JSON object with a
 *  string detail — caller falls back to err.message. */
function extractDetail(err: ApiError): string | null {
  try {
    const parsed = JSON.parse(err.body) as { detail?: unknown };
    if (typeof parsed?.detail === "string") return parsed.detail;
  } catch {
    /* not JSON — fall through */
  }
  return null;
}

/** Resolve every `source`-kind input slot's `source_slot_id` to the
 *  bound session-image id. The backend has no view of the SourceSlot
 *  table (it's localStorage-only), so we hand it the resolved map.
 *  Slots with no slot bound, or a slot without an image, are sent as
 *  `null` so the server can render a per-slot warning rather than
 *  silently dropping context. Keys are the input-slot ids stored
 *  under `model_params.__input_slots[].id`. */
function resolveSourceOverrides(
  agent: Agent,
  sourceSlots: SourceSlot[],
): Record<string, string | null> {
  const params = agent.model_params;
  if (!params || typeof params !== "object") return {};
  const raw = (params as Record<string, unknown>)["__input_slots"];
  if (!Array.isArray(raw)) return {};
  const out: Record<string, string | null> = {};
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    if (e.kind !== "source" || typeof e.id !== "string") continue;
    const cfg = (e.source ?? null) as Record<string, unknown> | null;
    const slotId =
      cfg && typeof cfg.source_slot_id === "string" ? cfg.source_slot_id : null;
    const slot = slotId
      ? sourceSlots.find((s) => s.id === slotId) ?? null
      : null;
    out[e.id] = slot?.source_image_id ?? null;
  }
  return out;
}

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
};

export type ComfyContextShape = {
  session: Session;
  // Real, server-backed (TanStack Query handles caching).
  agents: Agent[];
  agentsLoading: boolean;
  slotMap: SlotMapResponse | null;
  slotMapLoading: boolean;
  // Browser-only.
  chat: ChatMessage[];
  jobs: JobSnapshot[];
  /** Per-session, browser-only source-slot table. Mock layer of
   *  indirection between agents and session source images — agents
   *  bind to slot ids, slots map to images. */
  sourceSlots: SourceSlot[];
  selectedAgentId: string | null;
  runningAgentIds: ReadonlySet<string>;
  /** Per-agent surface for the most recent /run failure. Cleared on
   *  the next successful run. */
  agentRunErrors: Record<string, string>;
  isRunningWorkflow: boolean;
  workflowGenerateError: string | null;
  // Actions.
  selectAgent: (id: string | null) => void;
  setSourceSlots: (slots: SourceSlot[]) => void;
  runAgent: (agentId: string) => Promise<void>;
  runWorkflow: () => Promise<void>;
  sendChat: (text: string) => Promise<void>;
  clearChat: () => void;
  deleteJob: (jobId: string) => void;
};

// eslint-disable-next-line react-refresh/only-export-components
export const ComfyContext = createContext<ComfyContextShape | null>(null);

export function ComfyProvider({
  session,
  children,
}: {
  session: Session;
  children: ReactNode;
}) {
  const sessionId = session.id;
  const queryClient = useQueryClient();
  const agentsQuery = useAgents(sessionId);
  const slotMapQuery = useSlotMap(sessionId);

  const agents = useMemo(() => agentsQuery.data ?? [], [agentsQuery.data]);
  const slotMap = slotMapQuery.data ?? null;

  // Browser-only state.
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [jobs, setJobs] = useState<JobSnapshot[]>(() => loadSnapshots(sessionId));
  const [sourceSlots, setSourceSlotsState] = useState<SourceSlot[]>(() =>
    loadSourceSlots(sessionId),
  );
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [runningAgentIds, setRunningAgentIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [agentRunErrors, setAgentRunErrors] = useState<Record<string, string>>(
    {},
  );
  const [isRunningWorkflow, setIsRunningWorkflow] = useState(false);
  const [workflowGenerateError, setWorkflowGenerateError] = useState<string | null>(
    null,
  );

  // Auto-select the first agent once one exists, to keep variants from
  // having to handle the "no selection" edge case at every render.
  useEffect(() => {
    if (selectedAgentId === null && agents.length > 0) {
      setSelectedAgentId(agents[0].id);
    }
    if (selectedAgentId && !agents.some((a) => a.id === selectedAgentId)) {
      // Selected agent was deleted — fall back to the first.
      setSelectedAgentId(agents[0]?.id ?? null);
    }
  }, [agents, selectedAgentId]);

  const selectAgent = useCallback((id: string | null) => {
    setSelectedAgentId(id);
  }, []);

  const setSourceSlots = useCallback(
    (slots: SourceSlot[]) => {
      const next = saveSourceSlots(sessionId, slots);
      setSourceSlotsState(next);
    },
    [sessionId],
  );

  const runAgent = useCallback(
    async (agentId: string) => {
      const agent = agents.find((a) => a.id === agentId);
      if (!agent) return;
      setRunningAgentIds((prev) => {
        const next = new Set(prev);
        next.add(agentId);
        return next;
      });
      setAgentRunErrors((prev) => {
        if (!(agentId in prev)) return prev;
        const next = { ...prev };
        delete next[agentId];
        return next;
      });
      try {
        // Auto+unbound and non-LLM kinds are filtered server-side
        // (see comfy_agent_runner._select_composable_slots). The
        // SourceSlot indirection (input slot id → source_slot_id →
        // session image id) lives client-side, so we resolve each
        // `source`-kind input slot here and pass the lookup table on.
        const sourceOverrides = resolveSourceOverrides(agent, sourceSlots);
        const updated = await comfyApi.runAgent(sessionId, agentId, {
          source_image_overrides: sourceOverrides,
        });
        queryClient.setQueryData<Agent[]>(
          comfyKeys.agents(sessionId),
          (current) =>
            (current ?? []).map((a) => (a.id === updated.id ? updated : a)),
        );
      } catch (err) {
        const message =
          err instanceof ApiError
            ? extractDetail(err) ?? err.message
            : err instanceof Error
            ? err.message
            : "Run failed";
        setAgentRunErrors((prev) => ({ ...prev, [agentId]: message }));
      } finally {
        setRunningAgentIds((prev) => {
          const next = new Set(prev);
          next.delete(agentId);
          return next;
        });
      }
    },
    [agents, sessionId, sourceSlots, queryClient],
  );

  const runWorkflow = useCallback(async () => {
    setWorkflowGenerateError(null);
    if (!slotMap) {
      setWorkflowGenerateError("Slot map not loaded yet.");
      return;
    }
    // Validate every binding=llm slot has a bound agent output with a
    // non-null last_value. Mirrors PR6's eventual server-side check.
    const llmSlots = slotMap.slot_map.slots.filter((s) => s.binding === "llm");
    const boundValues: Record<string, unknown> = {};
    const missing: string[] = [];
    for (const ws of llmSlots) {
      let found = false;
      for (const a of agents) {
        for (const out of a.output_slots) {
          if (
            out.bound_to?.workflow_slot_label === ws.label &&
            out.last_value !== null &&
            out.last_value !== undefined
          ) {
            boundValues[ws.label] = out.last_value;
            found = true;
            break;
          }
        }
        if (found) break;
      }
      if (!found) missing.push(ws.label);
    }
    if (missing.length > 0) {
      setWorkflowGenerateError(
        `Missing values for: ${missing.join(", ")}. Run the agents that fill these slots.`,
      );
      return;
    }
    // Frozen + user_image slots round out the snapshot. user_image
    // slots resolve via metadata.source_slot_id → SourceSlot.id →
    // SourceSlot.source_image_id → session.source_images.id. Empty
    // pointers fall back to "(no image)" (the user is expected to
    // configure a source slot before they generate).
    for (const ws of slotMap.slot_map.slots) {
      const meta = (ws.metadata ?? {}) as Record<string, unknown>;
      if (ws.binding === "frozen") {
        boundValues[ws.label] = meta.value;
      } else if (ws.binding === "user_image") {
        const slotId =
          typeof meta.source_slot_id === "string" ? meta.source_slot_id : null;
        const ss = slotId
          ? sourceSlots.find((s) => s.id === slotId) ?? null
          : null;
        const image = ss?.source_image_id
          ? session.source_images.find((s) => s.id === ss.source_image_id)
          : null;
        boundValues[ws.label] = image?.original_filename ?? "(no image)";
      }
    }

    setIsRunningWorkflow(true);
    try {
      await new Promise((resolve) =>
        setTimeout(resolve, WORKFLOW_QUEUE_DELAY_MS),
      );
      const jobId = crypto.randomUUID();
      const resultDataUrl = renderFakeResult({
        jobId,
        workflowName: session.name ?? "untitled",
        boundValues,
      });
      const snapshot: JobSnapshot = {
        id: jobId,
        createdAt: Date.now(),
        workflowId: session.comfy_workflow_id ?? "",
        workflowName: session.name ?? "untitled",
        slotMap: slotMap.slot_map,
        agents: agents.map((a) => ({ ...a })),
        sources: session.source_images.map((s) => ({
          id: s.id,
          original_filename: s.original_filename,
          image_number: s.image_number,
          is_main: s.is_main,
          url: s.url,
        })),
        boundValues,
        resultDataUrl,
        status: "success",
      };
      const next = saveSnapshot(sessionId, snapshot);
      setJobs(next);
    } finally {
      setIsRunningWorkflow(false);
    }
  }, [agents, session, sessionId, slotMap, sourceSlots]);

  const sendChat = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
      createdAt: Date.now(),
    };
    setChat((prev) => [...prev, userMsg]);
    const reply = await emulateChatReply(trimmed);
    const replyMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: reply,
      createdAt: Date.now(),
    };
    setChat((prev) => [...prev, replyMsg]);
  }, []);

  const clearChat = useCallback(() => setChat([]), []);

  const deleteJob = useCallback(
    (jobId: string) => {
      const next = removeSnapshot(sessionId, jobId);
      setJobs(next);
    },
    [sessionId],
  );

  const value = useMemo<ComfyContextShape>(
    () => ({
      session,
      agents,
      agentsLoading: agentsQuery.isLoading,
      slotMap,
      slotMapLoading: slotMapQuery.isLoading,
      chat,
      jobs,
      sourceSlots,
      selectedAgentId,
      runningAgentIds,
      agentRunErrors,
      isRunningWorkflow,
      workflowGenerateError,
      selectAgent,
      setSourceSlots,
      runAgent,
      runWorkflow,
      sendChat,
      clearChat,
      deleteJob,
    }),
    [
      session,
      agents,
      agentsQuery.isLoading,
      slotMap,
      slotMapQuery.isLoading,
      chat,
      jobs,
      sourceSlots,
      selectedAgentId,
      runningAgentIds,
      agentRunErrors,
      isRunningWorkflow,
      workflowGenerateError,
      selectAgent,
      setSourceSlots,
      runAgent,
      runWorkflow,
      sendChat,
      clearChat,
      deleteJob,
    ],
  );

  return (
    <ComfyContext.Provider value={value}>
      {children}
    </ComfyContext.Provider>
  );
}
