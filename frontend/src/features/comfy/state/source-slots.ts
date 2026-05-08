/** Per-session "source slots" — a layer of indirection between agents
 *  and session source images.
 *
 *  Today an agent's source-input picks an image directly. Once we
 *  start composing multi-step / multi-agent flows, the same image
 *  will be referenced from many places (one VL pass for "main",
 *  another for "ref_in_scene", and so on). A slot table fixes that:
 *  agents bind to a slot id, slots map to an image and carry a
 *  purpose (main / scene reference / text-only reference) plus a
 *  human-readable key.
 *
 *  This is a frontend-only mock persisted in localStorage keyed by
 *  session.id. When the real Source-slot table lands on the backend,
 *  this file is the migration canary. See
 *  docs/comfy-agents-ui-mock-plan.md.
 */

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

export type SourceSlot = {
  id: string;
  key: string; // unique within session; auto-numbered "Image N" by default
  purpose: SourcePurpose;
  description: string | null;
  source_image_id: string | null; // bound session.source_images.id, or null
};

const STORAGE_PREFIX = "comfymock:source-slots:";

function storageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
}

export function loadSourceSlots(sessionId: string): SourceSlot[] {
  try {
    const raw = localStorage.getItem(storageKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidSourceSlot);
  } catch {
    return [];
  }
}

export function saveSourceSlots(
  sessionId: string,
  slots: SourceSlot[],
): SourceSlot[] {
  try {
    if (slots.length === 0) {
      localStorage.removeItem(storageKey(sessionId));
    } else {
      localStorage.setItem(storageKey(sessionId), JSON.stringify(slots));
    }
  } catch {
    /* quota — silent. The next save attempt will retry. */
  }
  return slots;
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

/** Build a fresh slot with an auto-numbered "Image N" key. The
 *  first slot gets purpose=main; subsequent slots default to
 *  ref_in_scene. */
export function makeSourceSlot(existing: SourceSlot[]): SourceSlot {
  const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  const key = nextImageKey(existing);
  const purpose: SourcePurpose = existing.length === 0 ? "main" : "ref_in_scene";
  return {
    id,
    key,
    purpose,
    description: null,
    source_image_id: null,
  };
}

/** Pick "Image N" with N = lowest unused integer ≥ 1 among existing
 *  keys that match `Image \d+`. Custom keys are ignored — if the user
 *  has renamed slots to anything else, we just pick the next number
 *  past their explicit "Image N"s. */
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

/** Look up a slot by its id (cheap; the list is short). Returns null
 *  when the slot was deleted or never existed. */
export function findSlot(
  slots: SourceSlot[],
  id: string | null | undefined,
): SourceSlot | null {
  if (!id) return null;
  return slots.find((s) => s.id === id) ?? null;
}
