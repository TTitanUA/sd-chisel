/**
 * Kind-aware LLM emulator. 10-second delay per call — long enough to feel
 * the loading states in each layout variant. Returns one fake value per
 * agent output slot, typed to the slot's `kind` (filled in at bind time
 * for `auto` slots).
 *
 * See docs/comfy-agents-ui-mock-plan.md.
 */
import type {
  Agent,
  AgentOutputSlot,
  CandidateInput,
  SlotKind,
} from "@/api/comfy";

export const LLM_EMULATOR_DELAY_MS = 10_000;

const POSITIVE_FILLER = [
  "soft cinematic lighting",
  "high detail, intricate",
  "warm colour grading",
  "85mm f/1.4",
  "depth of field",
];

const NEGATIVE_FILLER = [
  "low quality",
  "blurry",
  "watermark",
  "extra fingers",
  "jpeg artefacts",
];

function pick<T>(arr: readonly T[], seed: number): T {
  return arr[seed % arr.length];
}

function hashStr(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function fakeTextValue(
  slot: AgentOutputSlot,
  agent: Agent,
): string {
  const isNegative = slot.preset === "negative" || /negative/i.test(slot.label);
  const filler = (isNegative ? NEGATIVE_FILLER : POSITIVE_FILLER).slice(
    0,
    3 + (hashStr(slot.id) % 3),
  );
  const head = agent.prompt.trim()
    ? `[${slot.label}] ${agent.prompt.trim()}`
    : `[${slot.label}] (no prompt)`;
  return `${head} — ${filler.join(", ")}.`;
}

function fakeNumber(
  slot: AgentOutputSlot,
  meta: Record<string, unknown> | undefined,
  isInt: boolean,
): number {
  const def = (meta?.default as number | undefined) ?? (isInt ? 20 : 1.0);
  const min = (meta?.min as number | undefined) ?? Number.NEGATIVE_INFINITY;
  const max = (meta?.max as number | undefined) ?? Number.POSITIVE_INFINITY;
  const seed = hashStr(slot.id);
  const nudge = isInt ? (seed % 5) - 2 : ((seed % 100) - 50) / 100;
  return Math.max(min, Math.min(max, def + nudge));
}

/**
 * Emulate a per-agent run against the workflow's candidate buckets.
 * The candidate buckets give us per-slot metadata (default, min/max,
 * options) so numeric / enum outputs land in plausible ranges.
 *
 * Resolves with `{ [slotId]: value }`. Unbound auto-slots without a
 * `kind` are skipped (the run leaves their `last_value` untouched).
 */
export async function emulateAgentRun(
  agent: Agent,
  candidates: Record<SlotKind, CandidateInput[]> | null,
): Promise<Record<string, unknown>> {
  await new Promise((resolve) => setTimeout(resolve, LLM_EMULATOR_DELAY_MS));

  const out: Record<string, unknown> = {};
  for (const slot of agent.output_slots) {
    if (!slot.kind) continue;
    const cand = slot.bound_to
      ? findCandidateForSlot(slot, candidates)
      : null;
    const meta = cand?.metadata as Record<string, unknown> | undefined;

    switch (slot.kind) {
      case "text":
      case "multiline_text":
        out[slot.id] = fakeTextValue(slot, agent);
        break;
      case "number_int":
        out[slot.id] = Math.round(fakeNumber(slot, meta, true));
        break;
      case "number_float":
        out[slot.id] = fakeNumber(slot, meta, false);
        break;
      case "boolean":
        out[slot.id] = (hashStr(slot.id) & 1) === 1;
        break;
      case "enum": {
        const opts = (meta?.options as unknown[] | undefined) ?? [];
        out[slot.id] = opts.length > 0 ? pick(opts, hashStr(slot.id)) : null;
        break;
      }
      case "image":
      case "image_alpha":
      case "lora_name":
      case "checkpoint_name":
        // Not produced by an LLM in the real flow; ComfyMock leaves them
        // alone so the user can observe the design's handling of "agent
        // didn't fill this slot".
        break;
    }
  }

  if (agent.loras_enabled) {
    out["__loras"] = [
      { name: "cinematic_light", weight: 0.8 },
      { name: "soft_shadow", weight: 0.5 },
    ];
  }
  return out;
}

function findCandidateForSlot(
  slot: AgentOutputSlot,
  candidates: Record<SlotKind, CandidateInput[]> | null,
): CandidateInput | null {
  if (!candidates || !slot.kind || !slot.bound_to) return null;
  // Best effort — match the candidate by kind. The slot's bound_to
  // carries only the workflow_slot_label, which we'd have to look up in
  // the slot map; for emulation purposes "any candidate of the right
  // kind" gives plausible metadata.
  const list = candidates[slot.kind] ?? [];
  return list[0] ?? null;
}
