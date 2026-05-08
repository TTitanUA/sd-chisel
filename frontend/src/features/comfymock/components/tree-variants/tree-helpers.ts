/** Shared row-build helpers for the tree-based slot-mapping variants.
 *
 *  Each variant in this directory wants the same input-per-node tree
 *  layout (with wired inputs hidden) but differs in how slot mapping
 *  is exposed. This file factors out the common pivot. See
 *  docs/comfy-agents-ui-mock-plan.md.
 */
import type {
  CandidateBuckets,
  CandidateInput,
  SlotDefinition,
  Workflow,
} from "@/api/comfy";

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

export type MappingNodeRow = {
  nodeId: string;
  classType: string;
  title: string | null;
  inputs: MappingInputRow[];
};

export function buildMappingRows(
  workflow: Workflow | null | undefined,
  draft: SlotDefinition[],
  candidates: CandidateBuckets | null,
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
      classType: node.class_type ?? "?",
      title:
        node._meta?.title && node._meta.title.trim() ? node._meta.title : null,
      inputs,
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
