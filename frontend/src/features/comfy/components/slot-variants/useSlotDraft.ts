/** Shared draft + save helper for the slot-mapping variants.
 *
 * Each variant in this directory renders the same `slotMap.slots`
 * differently. They all need the same editing operations — rename
 * label, swap binding, edit frozen metadata.value, delete — and the
 * same dirty/save bookkeeping. This hook centralises that so the
 * variant components can stay focused on layout. See
 * docs/comfy-agents-ui-mock-plan.md.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ALLOWED_BINDINGS,
  useSaveSlotMap,
  useSlotMap,
  type SlotBinding,
  type SlotDefinition,
} from "@/api/comfy";

export type SlotPatch = Partial<SlotDefinition>;

export type SlotDraftHelpers = {
  /** null while the slot map query is loading. */
  draft: SlotDefinition[] | null;
  /** Server-side slots — for diff / reset. */
  serverSlots: SlotDefinition[] | null;
  isLoading: boolean;
  isEmptyAfterLoad: boolean;
  dirty: boolean;
  save: () => void;
  /** Save the current draft and return a Promise that resolves when
   *  the server has accepted it. Used by code paths that need to
   *  reference newly-created slot labels in another mutation (e.g.
   *  binding an agent's output to a freshly-added workflow slot —
   *  the agent PATCH would 422 if the label isn't in the server's
   *  slot_map yet). */
  saveAsync: () => Promise<unknown>;
  reset: () => void;
  saving: boolean;
  saveError: string | null;
  saved: boolean;
  patchSlot: (index: number, patch: SlotPatch) => void;
  setBinding: (index: number, binding: SlotBinding) => void;
  setFrozenValue: (index: number, value: unknown) => void;
  deleteSlot: (index: number) => void;
  appendSlot: (slot: SlotDefinition) => void;
};

export function useSlotDraft(sessionId: string): SlotDraftHelpers {
  const query = useSlotMap(sessionId);
  const save = useSaveSlotMap(sessionId);

  const serverSlots = query.data?.slot_map.slots ?? null;
  const [draft, setDraft] = useState<SlotDefinition[] | null>(null);

  // Re-sync draft when the server slots change *and* we have no local
  // edits — otherwise we'd clobber pending user changes on every
  // refetch. The cheap dirty check uses JSON equality of the previous
  // server slots to spot true server-side updates.
  useEffect(() => {
    if (!serverSlots) return;
    setDraft((prev) => {
      if (prev === null) return serverSlots;
      // If draft equals server, refresh to the latest server snapshot
      // so refetches reach us. Otherwise leave the user's edits alone.
      if (JSON.stringify(prev) === JSON.stringify(serverSlots)) {
        return serverSlots;
      }
      return prev;
    });
  }, [serverSlots]);

  const dirty = useMemo(() => {
    if (!draft || !serverSlots) return false;
    return JSON.stringify(draft) !== JSON.stringify(serverSlots);
  }, [draft, serverSlots]);

  const patchSlot = useCallback((index: number, patch: SlotPatch) => {
    setDraft((prev) =>
      prev ? prev.map((s, i) => (i === index ? { ...s, ...patch } : s)) : prev,
    );
  }, []);

  const setBinding = useCallback((index: number, binding: SlotBinding) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = [...prev];
      const slot = next[index];
      if (!slot) return prev;
      // Only allow legal bindings for this kind.
      if (!ALLOWED_BINDINGS[slot.kind].includes(binding)) return prev;
      const patch: SlotPatch = { binding };
      if (binding === "frozen" && slot.binding !== "frozen") {
        // Seed an empty frozen value when toggling on; the actual default
        // would need the candidate map but we keep this hook UI-agnostic.
        patch.metadata = { ...slot.metadata, value: defaultFrozen(slot) };
      } else if (slot.binding === "frozen" && binding !== "frozen") {
        const rest = { ...slot.metadata } as Record<string, unknown>;
        delete rest.value;
        patch.metadata = rest;
      }
      next[index] = { ...slot, ...patch };
      return next;
    });
  }, []);

  const setFrozenValue = useCallback((index: number, value: unknown) => {
    setDraft((prev) =>
      prev
        ? prev.map((s, i) =>
            i === index
              ? { ...s, metadata: { ...s.metadata, value } }
              : s,
          )
        : prev,
    );
  }, []);

  const deleteSlot = useCallback((index: number) => {
    setDraft((prev) => (prev ? prev.filter((_, i) => i !== index) : prev));
  }, []);

  const appendSlot = useCallback((slot: SlotDefinition) => {
    setDraft((prev) => (prev ? [...prev, slot] : [slot]));
  }, []);

  const doSave = useCallback(() => {
    if (!draft) return;
    save.mutate(draft);
  }, [draft, save]);

  const doSaveAsync = useCallback(() => {
    if (!draft) return Promise.resolve(null);
    return save.mutateAsync(draft);
  }, [draft, save]);

  const doReset = useCallback(() => {
    if (serverSlots) setDraft(serverSlots);
  }, [serverSlots]);

  return {
    draft,
    serverSlots,
    isLoading: query.isLoading,
    isEmptyAfterLoad: !!serverSlots && serverSlots.length === 0,
    dirty,
    save: doSave,
    saveAsync: doSaveAsync,
    reset: doReset,
    saving: save.isPending,
    saveError: save.isError ? (save.error as Error).message : null,
    saved: save.isSuccess && !dirty,
    patchSlot,
    setBinding,
    setFrozenValue,
    deleteSlot,
    appendSlot,
  };
}

function defaultFrozen(slot: SlotDefinition): unknown {
  switch (slot.kind) {
    case "boolean":
      return false;
    case "number_int":
    case "number_float":
      return 0;
    default:
      return "";
  }
}
