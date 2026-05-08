/** Shared slot-creation utilities for the mapping variants.
 *  Pulled out so every variant uses the same label-collision and
 *  default-binding logic. See docs/comfy-agents-ui-mock-plan.md. */
import {
  DEFAULT_BINDING,
  SLOT_KINDS,
  type Agent,
  type CandidateBuckets,
  type CandidateInput,
  type SlotBinding,
  type SlotDefinition,
  type SlotKind,
} from "@/api/comfy";
import type { Session } from "@/api/sessions";
import type { SourceSlot } from "../../state/source-slots";

/** Look up which agent (if any) has an output slot bound to the given
 *  workflow slot label. Used by panels to surface filler info next to
 *  every binding=llm row so the user can see end-to-end coverage. */
export type SlotFiller = {
  agentName: string;
  agentId: string;
  outputLabel: string;
  hasValue: boolean;
};

export function fillerFor(
  workflowSlotLabel: string,
  agents: Agent[],
): SlotFiller | null {
  for (const a of agents) {
    for (const s of a.output_slots) {
      if (s.bound_to?.workflow_slot_label === workflowSlotLabel) {
        return {
          agentName: a.name,
          agentId: a.id,
          outputLabel: s.label,
          hasValue: s.last_value !== null && s.last_value !== undefined,
        };
      }
    }
  }
  return null;
}

/** Agent outputs that are eligible to fill the given workflow slot.
 *
 *  Compatible outputs are:
 *  - Custom outputs whose `kind` matches the workflow slot's `kind`.
 *  - Auto outputs with `kind == null` — those resolve their kind at
 *    bind time, so they're always eligible.
 *  - Preset outputs (positive / negative) when the workflow slot is
 *    a multiline_text — preset kinds are fixed to multiline_text on
 *    the backend.
 *
 *  Returns one entry per (agent, output) pair, with flags showing
 *  whether the output is currently bound to this workflow slot or to
 *  some other workflow slot. UIs use the latter to greys out / warn
 *  on options the user would steal away from another binding. */
export type CompatibleOutput = {
  agentId: string;
  agentName: string;
  outputId: string;
  outputLabel: string;
  origin: import("@/api/comfy").SlotOriginKind;
  outputKind: SlotKind | null;
  isCurrentlyBound: boolean;
  isBoundElsewhere: boolean;
};

export function compatibleOutputsFor(
  workflowSlot: SlotDefinition,
  agents: Agent[],
): CompatibleOutput[] {
  const out: CompatibleOutput[] = [];
  for (const a of agents) {
    for (const o of a.output_slots) {
      const compatible =
        o.kind === workflowSlot.kind ||
        (o.origin === "auto" && o.kind === null);
      if (!compatible) continue;
      const boundLabel = o.bound_to?.workflow_slot_label ?? null;
      out.push({
        agentId: a.id,
        agentName: a.name,
        outputId: o.id,
        outputLabel: o.label,
        origin: o.origin,
        outputKind: o.kind,
        isCurrentlyBound: boundLabel === workflowSlot.label,
        isBoundElsewhere: boundLabel !== null && boundLabel !== workflowSlot.label,
      });
    }
  }
  return out;
}

/** Per-`binding=user_image` workflow slot, resolve the metadata
 *  reference to the session's source slot table. Three states match
 *  FillerHint's pattern:
 *  - **ready**: source slot exists and has an image bound.
 *  - **pending**: source slot exists but is still unbound.
 *  - **unbound**: workflow slot has no source-slot reference at all,
 *    or the referenced slot was deleted. */
export type SourceFiller = {
  slotId: string;
  slotKey: string;
  purpose: SourceSlot["purpose"];
  imageFilename: string | null;
};

export function sourceFillerFor(
  workflowSlot: SlotDefinition,
  sourceSlots: SourceSlot[],
  session: Session,
): SourceFiller | null {
  const meta = workflowSlot.metadata as Record<string, unknown> | undefined;
  const slotId = typeof meta?.source_slot_id === "string" ? meta.source_slot_id : null;
  if (!slotId) return null;
  const sourceSlot = sourceSlots.find((s) => s.id === slotId);
  if (!sourceSlot) return null;
  const image = sourceSlot.source_image_id
    ? session.source_images.find((i) => i.id === sourceSlot.source_image_id)
    : null;
  return {
    slotId,
    slotKey: sourceSlot.key,
    purpose: sourceSlot.purpose,
    imageFilename: image?.original_filename ?? null,
  };
}

/** Build a fresh SlotDefinition seeded from a candidate input.
 *  Picks a unique label by suffixing _2, _3, … if needed. */
export function slotFromCandidate(
  candidate: CandidateInput,
  draft: SlotDefinition[],
  binding?: SlotBinding,
): SlotDefinition {
  const taken = new Set(draft.map((s) => s.label));
  const baseLabel = `${candidate.node_class_type}_${candidate.input_name}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  let label = baseLabel || "slot";
  let n = 2;
  while (taken.has(label)) label = `${baseLabel}_${n++}`;
  const finalBinding = binding ?? DEFAULT_BINDING[candidate.kind];
  return {
    label,
    group: null,
    ordinal: draft.length + 1,
    description: null,
    kind: candidate.kind,
    origin: {
      node_id: candidate.node_id,
      input_name: candidate.input_name,
    },
    binding: finalBinding,
    metadata: finalBinding === "frozen" ? { value: defaultFrozen(candidate) } : {},
  };
}

/** Filter candidates to ones not already mapped in the draft. */
export function unboundCandidates(
  candidates: CandidateBuckets,
  draft: SlotDefinition[],
): CandidateBuckets {
  const bound = new Set(
    draft.map((s) => `${s.origin.node_id}:${s.origin.input_name}`),
  );
  const out = {} as CandidateBuckets;
  for (const kind of SLOT_KINDS) {
    out[kind] = (candidates[kind] ?? []).filter(
      (c) => !bound.has(`${c.node_id}:${c.input_name}`),
    );
  }
  return out;
}

export function totalUnbound(candidates: CandidateBuckets): number {
  let n = 0;
  for (const k of Object.keys(candidates) as SlotKind[]) {
    n += candidates[k]?.length ?? 0;
  }
  return n;
}

function defaultFrozen(c: CandidateInput): unknown {
  if (c.current_value !== undefined && c.current_value !== null) {
    return c.current_value;
  }
  const md = (c.metadata ?? {}) as Record<string, unknown>;
  if ("default" in md) return md.default;
  switch (c.kind) {
    case "boolean":
      return false;
    case "number_int":
    case "number_float":
      return 0;
    default:
      return "";
  }
}
