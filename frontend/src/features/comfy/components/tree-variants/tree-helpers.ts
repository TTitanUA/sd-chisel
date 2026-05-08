/** Shared row-build helpers for the tree-based slot-mapping variants.
 *
 *  Each variant in this directory wants the same input-per-node tree
 *  layout (with wired inputs hidden) but differs in how slot mapping
 *  is exposed. This file factors out the common pivot. See
 *  docs/comfy-agents-ui-mock-plan.md.
 */
import {
  IMAGE_SAVER_CLASSES,
  type Agent,
  type CandidateBuckets,
  type CandidateInput,
  type OutputSlotMapV1,
  type SlotDefinition,
  type Workflow,
} from "@/api/comfy";
import type { Session } from "@/api/sessions";
import type { SourceSlot } from "../../state/source-slots";

export type MappingInputRow = {
  name: string;
  rawValue: unknown;
  /** The candidate descriptor (kind, metadata) if this input is mappable.
   *  null for wired inputs (already filtered out) or unsupported types. */
  candidate: CandidateInput | null;
  /** The current draft slot for this input, if any. */
  mappedSlot: SlotDefinition | null;
  /** The index of the mapped slot in `helpers.draft` — used to call the
   *  patch / setBinding / deleteSlot helpers. */
  mappedIndex: number | null;
};

/** Marks a node whose inputs sd-chisel deliberately blocks from the
 *  slot map. PR-2 only marks ``IMAGE_SAVER_CLASSES`` (SaveImage) — those
 *  nodes are owned by the output slot map and their literal inputs
 *  (``filename_prefix``) seed the output label, so we don't let users
 *  accidentally LLM-compose them. ``outputLabel`` is set when the node
 *  is included in the live output slot map; ``null`` when the SaveImage
 *  exists in the workflow but the user has excluded it from outputs.
 *  Either way the inputs stay locked. */
export type OutputSaverInfo = {
  outputLabel: string | null;
};

export type MappingNodeRow = {
  nodeId: string;
  classType: string;
  title: string | null;
  inputs: MappingInputRow[];
  outputSaver: OutputSaverInfo | null;
};

export function buildMappingRows(
  workflow: Workflow | null | undefined,
  draft: SlotDefinition[],
  candidates: CandidateBuckets | null,
  outputSlotMap: OutputSlotMapV1 | null = null,
): MappingNodeRow[] {
  if (!workflow) return [];

  // Look up tables: candidate-by-origin and slot-by-origin.
  const candidateByOrigin = new Map<string, CandidateInput>();
  if (candidates) {
    for (const list of Object.values(candidates)) {
      for (const c of list) {
        candidateByOrigin.set(`${c.node_id}:${c.input_name}`, c);
      }
    }
  }
  const slotByOrigin = new Map<
    string,
    { slot: SlotDefinition; index: number }
  >();
  draft.forEach((slot, index) => {
    slotByOrigin.set(
      `${slot.origin.node_id}:${slot.origin.input_name}`,
      { slot, index },
    );
  });

  // node_id → output label, populated for SaveImage nodes the user
  // included in the output slot map.
  const outputLabelByNodeId = new Map<string, string>();
  if (outputSlotMap) {
    for (const o of outputSlotMap.outputs) {
      outputLabelByNodeId.set(o.node_id, o.label);
    }
  }

  const ids = Object.keys(workflow.graph).sort((a, b) => {
    const na = parseInt(a, 10);
    const nb = parseInt(b, 10);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    return a.localeCompare(b);
  });

  const out: MappingNodeRow[] = [];
  for (const id of ids) {
    const node = workflow.graph[id] as
      | {
          class_type?: string;
          inputs?: Record<string, unknown>;
          _meta?: { title?: string };
        }
      | undefined;
    if (!node || typeof node !== "object") continue;
    const classType = node.class_type ?? "?";
    const isSaver = IMAGE_SAVER_CLASSES.has(classType);
    const inputs: MappingInputRow[] = [];
    for (const [name, rawValue] of Object.entries(node.inputs ?? {})) {
      if (isWired(rawValue)) continue;
      const key = `${id}:${name}`;
      const mapped = slotByOrigin.get(key) ?? null;
      const candidate = candidateByOrigin.get(key) ?? null;
      // Skip inputs that are neither candidates nor mapped — they're
      // unsupported types and clutter the tree without offering action.
      if (!candidate && !mapped) continue;
      inputs.push({
        name,
        rawValue,
        candidate,
        mappedSlot: mapped?.slot ?? null,
        mappedIndex: mapped?.index ?? null,
      });
    }
    if (inputs.length === 0) continue;
    out.push({
      nodeId: id,
      classType,
      title:
        node._meta?.title && node._meta.title.trim() ? node._meta.title : null,
      inputs,
      outputSaver: isSaver
        ? { outputLabel: outputLabelByNodeId.get(id) ?? null }
        : null,
    });
  }
  return out;
}

export function isWired(v: unknown): boolean {
  return (
    Array.isArray(v) &&
    v.length === 2 &&
    typeof v[0] === "string" &&
    typeof v[1] === "number"
  );
}

export function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v.length > 64 ? v.slice(0, 64) + "…" : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "(?)";
  }
}

/** Render a value as a full plain-text string for the side drawer's
 *  readonly textareas — no truncation, multiline JSON for objects. */
export function formatValueFull(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return "(?)";
  }
}

/** What the workflow actually receives at Generate time, given the
 *  current state of the slot map + agent outputs + session sources.
 *  - Unmapped inputs keep the workflow's stored value.
 *  - `frozen` slots take their `metadata.value`.
 *  - `llm` slots resolve through whichever agent output is bound to
 *    the slot's label and fall back to ``null`` until an agent has
 *    been run. We never substitute a placeholder string here — the
 *    UI layer chooses how to render "no value yet".
 *  - `user_image` slots resolve `metadata.source_slot_id` →
 *    SourceSlot → session image; the displayable value is the
 *    image's filename (or ``null`` if the slot is unbound). */
export type LiveValueResult = {
  value: unknown;
  source: "workflow" | "frozen" | "llm" | "user_image" | "library_loras";
};

export function resolveLiveValue(
  input: MappingInputRow,
  ctx: {
    agents: Agent[];
    sourceSlots: SourceSlot[];
    session: Session;
  },
): LiveValueResult {
  const slot = input.mappedSlot;
  if (!slot) return { value: input.rawValue, source: "workflow" };

  if (slot.binding === "frozen") {
    const meta = (slot.metadata ?? {}) as Record<string, unknown>;
    return { value: meta.value ?? null, source: "frozen" };
  }
  if (slot.binding === "llm") {
    for (const a of ctx.agents) {
      for (const out of a.output_slots) {
        if (out.bound_to?.workflow_slot_label === slot.label) {
          return { value: out.last_value ?? null, source: "llm" };
        }
      }
    }
    return { value: null, source: "llm" };
  }
  if (slot.binding === "user_image") {
    const meta = (slot.metadata ?? {}) as Record<string, unknown>;
    const sourceSlotId =
      typeof meta.source_slot_id === "string" ? meta.source_slot_id : null;
    const ss = sourceSlotId
      ? ctx.sourceSlots.find((s) => s.id === sourceSlotId) ?? null
      : null;
    const image = ss?.source_image_id
      ? ctx.session.source_images.find((i) => i.id === ss.source_image_id) ??
        null
      : null;
    return {
      value: image?.original_filename ?? null,
      source: "user_image",
    };
  }
  return { value: null, source: "library_loras" };
}
