/**
 * localStorage-backed job-snapshot store. One entry per workflow run;
 * each captures the full state that produced the output so the user
 * can review "how did this image come about" later.
 *
 * Keyed by session id. LRU at 50 entries per session — older drop
 * silently. See docs/comfy-agents-ui-mock-plan.md.
 */
import type {
  Agent,
  SlotMapV2,
} from "@/api/comfy";
import type { SourceImage } from "@/api/sessions";

export type JobSnapshotStatus = "success" | "error";

export type JobSnapshot = {
  id: string;
  createdAt: number;
  workflowId: string;
  workflowName: string;
  slotMap: SlotMapV2;
  agents: Agent[];
  /** Sources at run time. We intentionally drop blob/data URLs from
   *  these (only metadata persists) since localStorage is small and
   *  the actual image bytes live in the session source store. */
  sources: Array<Pick<
    SourceImage,
    "id" | "original_filename" | "image_number" | "is_main" | "url"
  >>;
  /** Resolved value for every workflow slot that fed the run, keyed
   *  by `workflow_slot_label`. Null entries mean "unbound, used the
   *  graph's baked literal". */
  boundValues: Record<string, unknown>;
  /** data:image/png URL produced by `renderFakeResult`. */
  resultDataUrl: string;
  status: JobSnapshotStatus;
  /** Set when status === 'error'. */
  errorMessage?: string;
};

const MAX_PER_SESSION = 50;

const key = (sessionId: string) => `comfymock:jobs:${sessionId}`;

export function loadSnapshots(sessionId: string): JobSnapshot[] {
  try {
    const raw = localStorage.getItem(key(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as JobSnapshot[];
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

export function saveSnapshot(
  sessionId: string,
  snapshot: JobSnapshot,
): JobSnapshot[] {
  const existing = loadSnapshots(sessionId);
  const next = [snapshot, ...existing].slice(0, MAX_PER_SESSION);
  try {
    localStorage.setItem(key(sessionId), JSON.stringify(next));
  } catch {
    // Quota exceeded — drop oldest until it fits.
    let trimmed = next;
    while (trimmed.length > 1) {
      trimmed = trimmed.slice(0, -1);
      try {
        localStorage.setItem(key(sessionId), JSON.stringify(trimmed));
        break;
      } catch {
        continue;
      }
    }
  }
  return next;
}

export function deleteSnapshot(sessionId: string, jobId: string): JobSnapshot[] {
  const next = loadSnapshots(sessionId).filter((s) => s.id !== jobId);
  localStorage.setItem(key(sessionId), JSON.stringify(next));
  return next;
}

export function clearSnapshots(sessionId: string): void {
  localStorage.removeItem(key(sessionId));
}
