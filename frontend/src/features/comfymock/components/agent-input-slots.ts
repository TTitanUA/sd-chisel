/** Frontend-only schema for an agent's *input* slots.
 *
 *  The backend's `Agent` schema doesn't model input slots yet — for
 *  the UI mock we stash them under `agent.model_params.__input_slots`
 *  (model_params is a free-form `Record<string, unknown>` so the
 *  backend just persists the JSON blob without validating it). When
 *  the real input-slot data model lands on the backend, this file is
 *  the canary that tells us where to migrate from.
 *
 *  Four kinds (matching the user's design):
 *
 *  - **source** — bind one of the session's source images, configure
 *    a vision-language analysis pass (model + params + prompt). Output
 *    of the VL pass is part of the agent's context at run time.
 *  - **prompt_guide** — pick a prompt-guide library entry. Either the
 *    auto-default for the agent's chosen model + generation type, or
 *    a specific guide id.
 *  - **system** — extra system-prompt text, appended to the agent's
 *    mandatory base system prompt.
 *  - **loras** — allow/deny list + filters scoping which LoRAs the
 *    agent is allowed to attach. Optionally targets a specific model
 *    family.
 */

export type InputSlotKind = "source" | "prompt_guide" | "system" | "loras";

export const INPUT_SLOT_KINDS: InputSlotKind[] = [
  "source",
  "prompt_guide",
  "system",
  "loras",
];

export const INPUT_SLOT_KIND_LABEL: Record<InputSlotKind, string> = {
  source: "Source",
  prompt_guide: "Model Prompt Guide",
  system: "System",
  loras: "LoRAs",
};

export const INPUT_SLOT_KIND_DESCRIPTION: Record<InputSlotKind, string> = {
  source: "Attach a source image and configure its VL analysis.",
  prompt_guide:
    "Pick a prompt guide for the chosen model and generation type, or any other from the library.",
  system: "Extra system-prompt text appended to the agent's base prompt.",
  loras:
    "Scope which LoRAs the agent may attach (allow/deny + filters), optionally per model family.",
};

export type SourceInputConfig = {
  /** References a per-session SourceSlot.id — see
   *  state/source-slots.ts. Replaces the old direct
   *  `source_id: SourceImage.id`; agents now bind to slots, slots
   *  bind to images. Old data with the legacy field name is read
   *  via the back-compat shim in `readInputSlots`. */
  source_slot_id: string | null;
  vl_model: string | null;
  vl_prompt: string;
  vl_temperature: number | null;
  vl_max_tokens: number | null;
};

export type PromptGuideInputConfig = {
  mode: "auto" | "manual";
  guide_id: string | null;
  generation_type: string | null;
};

export type SystemInputConfig = {
  text: string;
};

export type LoraFilter = {
  field: "tag" | "trigger" | "model_family" | "name";
  match: string;
};

export type LoraInputConfig = {
  mode: "allow" | "deny";
  list: string[];
  filters: LoraFilter[];
  model_family: string | null;
};

export type AgentInputSlot = {
  id: string;
  kind: InputSlotKind;
  label: string;
  description: string | null;
  source?: SourceInputConfig;
  prompt_guide?: PromptGuideInputConfig;
  system?: SystemInputConfig;
  loras?: LoraInputConfig;
};

const STORAGE_KEY = "__input_slots";

/** Read the agent's input slots out of model_params. Tolerant of
 *  missing / malformed payloads — returns [] in those cases. Also
 *  migrates legacy `source.source_id` (which used to point at a
 *  session image directly) to the new `source.source_slot_id`. The
 *  old image ids have no direct mapping, so the migrated record
 *  starts unbound; the user just re-picks a slot. */
export function readInputSlots(
  modelParams: Record<string, unknown> | null,
): AgentInputSlot[] {
  if (!modelParams) return [];
  const raw = modelParams[STORAGE_KEY];
  if (!Array.isArray(raw)) return [];
  return raw.filter(isValidInputSlot).map(migrateLegacyShape);
}

function migrateLegacyShape(slot: AgentInputSlot): AgentInputSlot {
  if (slot.kind !== "source" || !slot.source) return slot;
  const src = slot.source as unknown as Record<string, unknown>;
  if ("source_id" in src && !("source_slot_id" in src)) {
    const { source_id: _drop, ...rest } = src;
    void _drop;
    return {
      ...slot,
      source: { ...(rest as Omit<SourceInputConfig, "source_slot_id">), source_slot_id: null },
    };
  }
  return slot;
}

/** Merge the input slots back into model_params, preserving any
 *  other keys that live there (sampling params, etc.). */
export function writeInputSlots(
  modelParams: Record<string, unknown> | null,
  slots: AgentInputSlot[],
): Record<string, unknown> | null {
  const base = (modelParams ?? {}) as Record<string, unknown>;
  if (slots.length === 0) {
    const { [STORAGE_KEY]: _drop, ...rest } = base;
    void _drop;
    return Object.keys(rest).length === 0 ? null : rest;
  }
  return { ...base, [STORAGE_KEY]: slots };
}

function isValidInputSlot(v: unknown): v is AgentInputSlot {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.label === "string" &&
    typeof o.kind === "string" &&
    INPUT_SLOT_KINDS.includes(o.kind as InputSlotKind)
  );
}

/** Build a fresh slot of the given kind with sensible defaults. */
export function makeInputSlot(kind: InputSlotKind): AgentInputSlot {
  const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  const base = {
    id,
    kind,
    label: defaultLabel(kind),
    description: null,
  };
  switch (kind) {
    case "source":
      return {
        ...base,
        kind,
        source: {
          source_slot_id: null,
          vl_model: null,
          vl_prompt: "Describe the subject, style, mood, and key visual elements.",
          vl_temperature: 0.3,
          vl_max_tokens: 512,
        },
      };
    case "prompt_guide":
      return {
        ...base,
        kind,
        prompt_guide: {
          mode: "auto",
          guide_id: null,
          generation_type: null,
        },
      };
    case "system":
      return {
        ...base,
        kind,
        system: { text: "" },
      };
    case "loras":
      return {
        ...base,
        kind,
        loras: {
          mode: "allow",
          list: [],
          filters: [],
          model_family: null,
        },
      };
  }
}

function defaultLabel(kind: InputSlotKind): string {
  return INPUT_SLOT_KIND_LABEL[kind].toLowerCase().replace(/\s+/g, "_");
}

/** Mock prompt-guide catalog — a real one will come from the
 *  prompt-guides library when that ships. Used by the prompt_guide
 *  input form so the user can pick from a list. */
export const MOCK_PROMPT_GUIDES = [
  { id: "auto", label: "Auto (model default)", families: ["*"] },
  { id: "sd1.5_classic", label: "SD 1.5 — classic style tags", families: ["sd15"] },
  { id: "sdxl_natural", label: "SDXL — natural language", families: ["sdxl"] },
  { id: "flux_dense", label: "Flux — dense paragraph", families: ["flux"] },
  { id: "flux_short", label: "Flux — short caption", families: ["flux"] },
  { id: "qwen_chat", label: "Qwen — chat-style", families: ["qwen"] },
];

export const MOCK_GENERATION_TYPES = [
  "t2i",
  "i2i",
  "inpaint",
  "controlnet",
  "upscale",
];

export const MOCK_MODEL_FAMILIES = ["sd15", "sdxl", "flux", "qwen", "any"];

export const MOCK_LORA_FILTER_FIELDS: LoraFilter["field"][] = [
  "tag",
  "trigger",
  "model_family",
  "name",
];
