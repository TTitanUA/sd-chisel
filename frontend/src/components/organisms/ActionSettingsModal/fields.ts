// Field registry for the per-action settings modal.
//
// Adding a new sampling parameter is a one-line change here — add an entry,
// the modal renders it automatically. The backend's allowed-keys list lives
// in backend/app/services/action_settings.py and must be kept in sync.

export type FieldKind = "number" | "integer";

export interface FieldDef {
  key: string;
  label: string;
  help: string;
  docHref: string;
  kind: FieldKind;
  min?: number;
  max?: number;
  step?: number;
}

export const FIELDS: readonly FieldDef[] = [
  {
    key: "temperature",
    label: "Temperature",
    help:
      "Controls randomness. 0 makes the model deterministic and repetitive — same prompt, same answer. " +
      "Higher values (around 0.7–1.0) loosen things up and give more variety; very high values (>1.2) start " +
      "to produce incoherent text. Lower it for analysis/summarization, raise it for creative prompts.",
    docHref: "https://lmstudio.ai/docs/developer/openai-compat/chat-completions",
    kind: "number",
    min: 0,
    max: 2,
    step: 0.05,
  },
  {
    key: "top_p",
    label: "Top-P (nucleus sampling)",
    help:
      "Caps the model to the smallest set of tokens whose combined probability is at least P. 1.0 disables it. " +
      "0.9 keeps only the most plausible options at every step — safer, less wandering. Use either temperature " +
      "or top_p, not both aggressively.",
    docHref: "https://platform.openai.com/docs/api-reference/chat/create#chat-create-top_p",
    kind: "number",
    min: 0,
    max: 1,
    step: 0.01,
  },
  {
    key: "top_k",
    label: "Top-K",
    help:
      "Hard limit on the number of tokens considered at each step. 40 is a common balance; 0 means \"no limit\" " +
      "(use top_p / temperature instead). Lower K → more focused, more repetitive.",
    docHref: "https://lmstudio.ai/docs/developer/openai-compat/chat-completions",
    kind: "integer",
    min: 0,
  },
  {
    key: "max_tokens",
    label: "Max tokens",
    help:
      "Cap on how many tokens the model is allowed to produce. Stops generation early — does not make the model " +
      "write longer answers. Leave empty to let the model decide. Useful to bound chat replies or summaries.",
    docHref: "https://platform.openai.com/docs/api-reference/chat/create#chat-create-max_tokens",
    kind: "integer",
    min: 1,
  },
  {
    key: "presence_penalty",
    label: "Presence penalty",
    help:
      "Range -2…2. Positive values discourage the model from reusing any topic/word that already appeared, " +
      "pushing it toward new subjects. Negative values do the opposite. Most users leave this at 0.",
    docHref: "https://platform.openai.com/docs/api-reference/chat/create#chat-create-presence_penalty",
    kind: "number",
    min: -2,
    max: 2,
    step: 0.05,
  },
  {
    key: "frequency_penalty",
    label: "Frequency penalty",
    help:
      "Range -2…2. Positive values penalize tokens proportionally to how often they have appeared, reducing " +
      "literal repetition. Use this if the model gets stuck repeating phrases.",
    docHref: "https://platform.openai.com/docs/api-reference/chat/create#chat-create-frequency_penalty",
    kind: "number",
    min: -2,
    max: 2,
    step: 0.05,
  },
  {
    key: "repeat_penalty",
    label: "Repeat penalty",
    help:
      "LM Studio / llama.cpp-style multiplicative repetition penalty. 1.0 = off. 1.05–1.15 is typical; values " +
      "much above 1.2 distort output. Independent from frequency_penalty.",
    docHref: "https://lmstudio.ai/docs/developer/openai-compat/chat-completions",
    kind: "number",
    min: 0,
    max: 2,
    step: 0.05,
  },
  {
    key: "seed",
    label: "Seed",
    help:
      "An integer that makes sampling reproducible — same prompt + same seed + same parameters → same output. " +
      "Useful for debugging or comparing prompt changes. Leave empty for random sampling.",
    docHref: "https://platform.openai.com/docs/api-reference/chat/create#chat-create-seed",
    kind: "integer",
  },
];

export const ACTION_LABELS = {
  analyze: "Analyze (image)",
  chat: "Chat",
  summarize: "Summarize",
  generate: "Generate prompt",
  comfy_import: "Import ComfyUI node",
} as const;
