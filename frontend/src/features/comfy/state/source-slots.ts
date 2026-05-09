/** Per-session source slots — display name + purpose + description +
 *  bound image. Until iter 8 these lived in localStorage; now the
 *  authoritative store is `comfy_session_source_slots` on the
 *  backend. This module exports the legacy types + UI constants so
 *  the panels can keep their existing shape, plus a one-time
 *  migration helper that copies any leftover localStorage entries
 *  into the server (preserving ids so workflow / agent references
 *  that point at them still resolve).
 */

import { comfyApi, type ServerSourceSlot } from "@/api/comfy";
import { ApiError } from "@/api/client";

export const SOURCE_PURPOSES = ["main", "ref_in_scene", "ref_text_only"] as const;
export type SourcePurpose = (typeof SOURCE_PURPOSES)[number];

export const SOURCE_PURPOSE_LABEL: Record<SourcePurpose, string> = {
  main: "Main",
  ref_in_scene: "Scene reference",
  ref_text_only: "Text-only reference",
};

export const SOURCE_PURPOSE_HINT: Record<SourcePurpose, string> = {
  main: "The primary subject. The composition revolves around this image.",
  ref_in_scene: "Visual reference that should appear inside the scene.",
  ref_text_only:
    "Reference used by VL analysis only, never composited into the scene.",
};

/** Legacy in-memory shape — what the SourcesPanel and ComfyProvider
 *  pass around. Maps 1-to-1 with `ServerSourceSlot` minus the
 *  audit columns; we strip those at the data-load boundary so panels
 *  stay agnostic. */
export type SourceSlot = {
  id: string;
  key: string;
  purpose: SourcePurpose;
  description: string | null;
  source_image_id: string | null;
};

export function fromServerSlot(s: ServerSourceSlot): SourceSlot {
  return {
    id: s.id,
    key: s.key,
    purpose: s.purpose as SourcePurpose,
    description: s.description,
    source_image_id: s.source_image_id,
  };
}

const STORAGE_PREFIX = "comfymock:source-slots:";

function storageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
}

function isValidSourceSlot(v: unknown): v is SourceSlot {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.key === "string" &&
    typeof o.purpose === "string" &&
    SOURCE_PURPOSES.includes(o.purpose as SourcePurpose) &&
    (o.description === null || typeof o.description === "string") &&
    (o.source_image_id === null || typeof o.source_image_id === "string")
  );
}

/** One-time migration: when the server returns no slots for a session
 *  but localStorage has some, POST them back (preserving ids), then
 *  clear localStorage. Idempotent — once the backend has any slot
 *  for the session, we never touch localStorage again.
 *
 *  Returns true when at least one slot was migrated; the caller can
 *  invalidate the slots query so the freshly-migrated rows render.
 */
export async function migrateLocalStorageSlots(
  sessionId: string,
  serverSlots: ServerSourceSlot[],
): Promise<boolean> {
  if (serverSlots.length > 0) {
    // Backend already authoritative — clear any stale localStorage
    // copy so subsequent reloads don't try to migrate twice.
    try {
      localStorage.removeItem(storageKey(sessionId));
    } catch {
      /* ignore */
    }
    return false;
  }
  let raw: string | null;
  try {
    raw = localStorage.getItem(storageKey(sessionId));
  } catch {
    return false;
  }
  if (!raw) return false;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return false;
  }
  if (!Array.isArray(parsed)) return false;
  const slots = parsed.filter(isValidSourceSlot);
  if (slots.length === 0) {
    try {
      localStorage.removeItem(storageKey(sessionId));
    } catch {
      /* ignore */
    }
    return false;
  }
  let migrated = 0;
  for (const [position, slot] of slots.entries()) {
    try {
      await comfyApi.createSourceSlot(sessionId, {
        id: slot.id,
        key: slot.key,
        purpose: slot.purpose,
        description: slot.description,
        source_image_id: slot.source_image_id,
        position,
      });
      migrated += 1;
    } catch (err) {
      // 409 on duplicate id / key means the server already has the
      // row — keep going. Anything else: bail; the user can retry by
      // reloading.
      if (err instanceof ApiError && err.status === 409) continue;
      console.warn("[source-slots] migration step failed", err);
      return false;
    }
  }
  try {
    localStorage.removeItem(storageKey(sessionId));
  } catch {
    /* ignore */
  }
  return migrated > 0;
}

/** Auto-numbered "Image N" key — same logic as before, used by the
 *  + slot button when creating fresh slots. The backend uses the same
 *  unique-key invariant, so callers can pass the suggested key
 *  through directly. */
export function nextImageKey(existing: SourceSlot[]): string {
  const taken = new Set<number>();
  for (const s of existing) {
    const m = /^Image (\d+)$/.exec(s.key);
    if (m) taken.add(parseInt(m[1], 10));
  }
  let n = 1;
  while (taken.has(n)) n++;
  return `Image ${n}`;
}

export function nextPurpose(existing: SourceSlot[]): SourcePurpose {
  return existing.length === 0 ? "main" : "ref_in_scene";
}

export function findSlot(
  slots: SourceSlot[],
  id: string | null | undefined,
): SourceSlot | null {
  if (!id) return null;
  return slots.find((s) => s.id === id) ?? null;
}
