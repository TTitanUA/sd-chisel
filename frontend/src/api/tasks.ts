import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "./client";

export type TaskKind = "reindex_lora" | "reindex_all" | "civitai_import";
export type TaskStatus =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export type Task = {
  id: string;
  kind: TaskKind;
  title: string;
  target: Record<string, unknown>;
  status: TaskStatus;
  progress: number | null;
  message: string | null;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
};

type TaskListResponse = { tasks: Task[] };

export const tasksKey = ["tasks", "active"] as const;

export const tasksApi = {
  listActive: () =>
    apiFetch<TaskListResponse>("/api/tasks?active_only=true").then(
      (r) => r.tasks,
    ),
};

export function useActiveTasks() {
  return useQuery({
    queryKey: tasksKey,
    queryFn: tasksApi.listActive,
    // Initial fetch only — the SSE subscription patches the cache after.
    staleTime: Infinity,
    refetchOnMount: true,
  });
}

/**
 * Subscribe to /api/tasks/stream and patch react-query's cache for active
 * tasks. Mount once near the app root. On `done` events, also invalidate
 * library queries so newly-indexed LoRAs flip `is_indexed=true` in the UI.
 */
export function useTaskStream() {
  const client = useQueryClient();

  useEffect(() => {
    const url = `${API_BASE}/api/tasks/stream`;
    const es = new EventSource(url);

    es.onmessage = (ev) => {
      let payload: SseEvent;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        return;
      }
      handleEvent(client, payload);
    };

    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do here. We don't surface
      // transient errors so a flaky network doesn't spam the UI.
    };

    return () => {
      es.close();
    };
  }, [client]);
}

type SseEvent =
  | { type: "snapshot"; tasks: Task[] }
  | { type: "added"; task: Task }
  | { type: "updated"; task: Task }
  | { type: "removed"; task: Task };

function handleEvent(
  client: ReturnType<typeof useQueryClient>,
  ev: SseEvent,
) {
  if (ev.type === "snapshot") {
    const active = ev.tasks.filter(
      (t) => t.status === "queued" || t.status === "running",
    );
    client.setQueryData<Task[]>(tasksKey, active);
    return;
  }

  client.setQueryData<Task[]>(tasksKey, (prev) => {
    const list = prev ?? [];
    const without = list.filter((t) => t.id !== ev.task.id);
    if (ev.task.status === "queued" || ev.task.status === "running") {
      return [...without, ev.task];
    }
    return without;
  });

  if (ev.task.status === "done" && ev.task.kind === "reindex_lora") {
    void client.invalidateQueries({ queryKey: ["library", "loras"] });
  }
  if (ev.task.status === "done" && ev.task.kind === "reindex_all") {
    void client.invalidateQueries({ queryKey: ["library"] });
  }
}

/** True when at least one reindex task is queued or running. */
export function useIsReindexing() {
  const tasks = useActiveTasks();
  return (tasks.data ?? []).some(
    (t) => t.kind === "reindex_lora" || t.kind === "reindex_all",
  );
}
