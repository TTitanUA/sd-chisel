/**
 * Comfy session state provider — bridges the real backend (agents,
 * slot map, jobs, Single Run pipeline) with the browser-only surfaces
 * still on this side (chat reference panel, source-slot indirection)
 * and exposes the action set every panel renders against.
 *
 * Single Run lifecycle:
 *   user clicks Single Run
 *     → `startSingleRun` mutation POSTs /single_run
 *     → on success we open an SSE stream against the returned URL
 *     → events flow into `runState.events` for the Run Viewer (iter 5)
 *     → on `stage=done` the stream closes, the jobs query invalidates,
 *       and the gallery picks up the new card
 */
import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  comfyApi,
  comfyKeys,
  subscribeToJobStream,
  useAgents,
  useDeleteJob,
  useJobs,
  useSlotMap,
  useStartSingleRun,
  type Agent,
  type ComfyJob,
  type ComfyRunEvent,
  type SlotMapResponse,
} from "@/api/comfy";
import { ApiError } from "@/api/client";
import type { Session } from "@/api/sessions";
import { emulateChatReply } from "../mocks/chat-emulator";
import {
  loadSourceSlots,
  saveSourceSlots,
  type SourceSlot,
} from "./source-slots";

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

/** Snapshot of an in-flight Single Run. Cleared once the server emits
 *  `stage=done` and the gallery query has reconciled. */
export type RunState = {
  jobId: string;
  generationId: string;
  events: ComfyRunEvent[];
  /** The latest stage we saw — `validate | snapshot | agents | unload_lm
   *  | upload_inputs | patch | queue | execute | save | cleanup | done`. */
  currentStage: string;
  /** True from the moment the POST resolves until `stage=done` arrives. */
  inProgress: boolean;
};

export type ComfyContextShape = {
  session: Session;
  // Real, server-backed (TanStack Query handles caching).
  agents: Agent[];
  agentsLoading: boolean;
  slotMap: SlotMapResponse | null;
  slotMapLoading: boolean;
  jobs: ComfyJob[];
  jobsLoading: boolean;
  // Browser-only — track A wires real chat; iter 3 (deferred) drops
  // the source-slot indirection.
  chat: ChatMessage[];
  /** Per-session, browser-only source-slot table. Mock layer of
   *  indirection between agents and session source images — agents
   *  bind to slot ids, slots map to images. */
  sourceSlots: SourceSlot[];
  selectedAgentId: string | null;
  runningAgentIds: ReadonlySet<string>;
  /** Per-agent surface for the most recent /run failure. Cleared on
   *  the next successful run. */
  agentRunErrors: Record<string, string>;
  /** Live Single Run state, or null when no run is in flight. */
  runState: RunState | null;
  /** Convenience: !!runState (older surface name kept stable so the
   *  agents-panel footer doesn't need to re-thread props). */
  isRunningWorkflow: boolean;
  workflowGenerateError: string | null;
  // Actions.
  selectAgent: (id: string | null) => void;
  setSourceSlots: (slots: SourceSlot[]) => void;
  runAgent: (agentId: string) => Promise<void>;
  runWorkflow: () => Promise<void>;
  /** Clear ``runState`` once the run terminates. The Run Viewer
   *  calls this when the user dismisses; the provider refuses while
   *  ``inProgress`` is true so the viewer's Close button is the
   *  only path to dismissal. */
  dismissRun: () => void;
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
  const jobsQuery = useJobs(sessionId);
  const startSingleRun = useStartSingleRun(sessionId);
  const deleteJobMutation = useDeleteJob(sessionId);

  const agents = useMemo(() => agentsQuery.data ?? [], [agentsQuery.data]);
  const slotMap = slotMapQuery.data ?? null;
  const jobs = useMemo(() => jobsQuery.data ?? [], [jobsQuery.data]);

  // Browser-only state — track A wires real chat; iter 3 (deferred)
  // cleans up the source-slot indirection.
  const [chat, setChat] = useState<ChatMessage[]>([]);
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
  const [runState, setRunState] = useState<RunState | null>(null);
  const [workflowGenerateError, setWorkflowGenerateError] = useState<string | null>(
    null,
  );
  const streamCleanupRef = useRef<(() => void) | null>(null);

  // Cancel any active SSE stream on unmount or session change so we
  // don't leak EventSources across the workspace lifetime.
  useEffect(() => {
    return () => {
      streamCleanupRef.current?.();
      streamCleanupRef.current = null;
    };
  }, [sessionId]);

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
    // Resolve image_bindings for every binding=user_image slot. The
    // backend takes a flat slot_label → session_image_id map; the
    // SourceSlot indirection (metadata.source_slot_id → slot.id →
    // image_id) lives client-side until iter 3 lands.
    const imageBindings: Record<string, string | null> = {};
    for (const ws of slotMap.slot_map.slots) {
      if (ws.binding !== "user_image") continue;
      const meta = (ws.metadata ?? {}) as Record<string, unknown>;
      const slotId =
        typeof meta.source_slot_id === "string" ? meta.source_slot_id : null;
      const ss = slotId
        ? sourceSlots.find((s) => s.id === slotId) ?? null
        : null;
      imageBindings[ws.label] = ss?.source_image_id ?? null;
    }

    try {
      const result = await startSingleRun.mutateAsync({
        image_bindings: imageBindings,
      });
      // Open the SSE stream and attach to runState; the orchestrator
      // emits per-stage events that the gallery / Run Viewer (iter 5)
      // pick up.
      streamCleanupRef.current?.();
      setRunState({
        jobId: result.job_id,
        generationId: result.generation_id,
        events: [],
        currentStage: "validate",
        inProgress: true,
      });
      const cleanup = subscribeToJobStream(
        result.job_id,
        (event) => {
          setRunState((prev) => {
            if (prev === null || prev.jobId !== result.job_id) return prev;
            const stage = typeof event.stage === "string"
              ? event.stage
              : prev.currentStage;
            const inProgress = !(
              event.stage === "done" ||
              (event.stage === "execute" && event.event === "failed")
            );
            return {
              ...prev,
              events: [...prev.events, event],
              currentStage: stage,
              inProgress,
            };
          });
          if (event.stage === "done") {
            // Pipeline finished — refresh gallery + agents (last_value
            // changed) and tear the stream down.
            void queryClient.invalidateQueries({
              queryKey: comfyKeys.jobs(sessionId),
            });
            void queryClient.invalidateQueries({
              queryKey: comfyKeys.agents(sessionId),
            });
            streamCleanupRef.current?.();
            streamCleanupRef.current = null;
          }
        },
        (err) => {
          // Stream torn down — either run finished and the channel
          // was reaped (refresh gallery to pick up the row) or a
          // transient drop. Mirror the error to the user; the gallery
          // refresh either way confirms what actually happened.
          setRunState((prev) =>
            prev ? { ...prev, inProgress: false } : prev,
          );
          setWorkflowGenerateError(err.message);
          void queryClient.invalidateQueries({
            queryKey: comfyKeys.jobs(sessionId),
          });
        },
      );
      streamCleanupRef.current = cleanup;
    } catch (err) {
      const message =
        err instanceof ApiError
          ? extractDetail(err) ?? err.message
          : err instanceof Error
          ? err.message
          : "Single Run failed";
      setWorkflowGenerateError(message);
    }
  }, [
    slotMap, sourceSlots, startSingleRun, sessionId, queryClient,
  ]);

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

  const dismissRun = useCallback(() => {
    setRunState((prev) => (prev && prev.inProgress ? prev : null));
  }, []);

  // Browser-level nav block while a run is in flight — the browser's
  // native confirm is a fallback; the workspace layout adds a router
  // blocker for the in-app navigation paths.
  useEffect(() => {
    if (!runState || !runState.inProgress) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [runState]);

  // Resume on reload — when the session has a comfy_jobs row in
  // status='running' on first load, the orchestrator may still be
  // alive on the backend. Hydrate runState from that row and try to
  // re-subscribe; the channel's replay snapshot fills the event log.
  useEffect(() => {
    if (runState !== null) return;
    const inflight = jobs.find((j) => j.status === "running");
    if (!inflight) return;
    setRunState({
      jobId: inflight.id,
      generationId: inflight.generation_id,
      events: [],
      currentStage: "validate",
      inProgress: true,
    });
    streamCleanupRef.current?.();
    const cleanup = subscribeToJobStream(
      inflight.id,
      (event) => {
        setRunState((prev) => {
          if (prev === null || prev.jobId !== inflight.id) return prev;
          const stage = typeof event.stage === "string"
            ? event.stage
            : prev.currentStage;
          const inProgress = !(
            event.stage === "done" ||
            (event.stage === "execute" && event.event === "failed")
          );
          return {
            ...prev,
            events: [...prev.events, event],
            currentStage: stage,
            inProgress,
          };
        });
        if (event.stage === "done") {
          void queryClient.invalidateQueries({
            queryKey: comfyKeys.jobs(sessionId),
          });
          streamCleanupRef.current?.();
          streamCleanupRef.current = null;
        }
      },
      () => {
        // Channel reaped — the run finished before we could resume.
        // Fall back to whatever the gallery shows.
        setRunState((prev) =>
          prev && prev.jobId === inflight.id
            ? { ...prev, inProgress: false }
            : prev,
        );
      },
    );
    streamCleanupRef.current = cleanup;
  }, [jobs, runState, sessionId, queryClient]);

  const deleteJob = useCallback(
    (jobId: string) => {
      deleteJobMutation.mutate(jobId);
    },
    [deleteJobMutation],
  );

  const isRunningWorkflow = runState !== null && runState.inProgress;

  const value = useMemo<ComfyContextShape>(
    () => ({
      session,
      agents,
      agentsLoading: agentsQuery.isLoading,
      slotMap,
      slotMapLoading: slotMapQuery.isLoading,
      jobs,
      jobsLoading: jobsQuery.isLoading,
      chat,
      sourceSlots,
      selectedAgentId,
      runningAgentIds,
      agentRunErrors,
      runState,
      isRunningWorkflow,
      workflowGenerateError,
      selectAgent,
      setSourceSlots,
      runAgent,
      runWorkflow,
      dismissRun,
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
      jobs,
      jobsQuery.isLoading,
      chat,
      sourceSlots,
      selectedAgentId,
      runningAgentIds,
      agentRunErrors,
      runState,
      isRunningWorkflow,
      workflowGenerateError,
      selectAgent,
      setSourceSlots,
      runAgent,
      runWorkflow,
      dismissRun,
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
