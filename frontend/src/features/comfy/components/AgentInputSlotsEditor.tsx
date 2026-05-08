/** Input-slots editor for one agent.
 *
 *  The agent declares which extra inputs feed its LLM call. Four
 *  kinds, each with its own tiny form (see ./agent-input-slots.ts):
 *
 *  - **source** — pick a session image + a VL model and prompt; at
 *    run time the VL pass turns the image into text for the agent.
 *  - **prompt_guide** — auto (use the chosen model + generation
 *    type's default) or a specific guide id from the library.
 *  - **system** — plain extra-system-prompt text.
 *  - **loras** — allow/deny scoping (list + filters + model family).
 *
 *  All four persist via `agent.model_params.__input_slots` — the
 *  backend doesn't know the schema, just stores the JSON. See
 *  docs/comfy-agents-ui-mock-plan.md.
 */
import { useEffect, useMemo, useState } from "react";
import { useUpdateAgent, type Agent } from "@/api/comfy";
import { useFamilies } from "@/api/library";
import { useLmModels } from "@/api/settings";
import { useComfy } from "../state/useComfy";
import {
  GENERATION_TYPES,
  INPUT_SLOT_KINDS,
  INPUT_SLOT_KIND_DESCRIPTION,
  INPUT_SLOT_KIND_LABEL,
  MOCK_LORA_FILTER_FIELDS,
  MOCK_MODEL_FAMILIES,
  makeInputSlot,
  readInputSlots,
  writeInputSlots,
  type AgentInputSlot,
  type InputSlotKind,
  type LoraFilter,
  type PromptGuideGenerationType,
} from "./agent-input-slots";
import styles from "./AgentInputSlotsEditor.module.css";

export function AgentInputSlotsEditor({ agent }: { agent: Agent }) {
  const { session } = useComfy();
  const update = useUpdateAgent(session.id);

  // Server-side slots (re-read whenever the agent record refreshes).
  const serverSlots = useMemo(
    () => readInputSlots(agent.model_params),
    [agent.model_params],
  );

  const [draft, setDraft] = useState<AgentInputSlot[]>(serverSlots);
  const [openSlotId, setOpenSlotId] = useState<string | null>(null);
  const [showKindPicker, setShowKindPicker] = useState(false);

  // Re-sync from server when no local edits are pending — same trick
  // as useSlotDraft. Otherwise refetches would clobber unsaved work.
  useEffect(() => {
    setDraft((prev) => {
      if (JSON.stringify(prev) === JSON.stringify(serverSlots)) {
        return serverSlots;
      }
      return prev;
    });
  }, [serverSlots]);

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(serverSlots),
    [draft, serverSlots],
  );

  function patchSlot(id: string, patch: Partial<AgentInputSlot>) {
    setDraft((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    );
  }
  function deleteSlot(id: string) {
    setDraft((prev) => prev.filter((s) => s.id !== id));
    if (openSlotId === id) setOpenSlotId(null);
  }
  function addSlot(kind: InputSlotKind) {
    const slot = makeInputSlot(kind);
    setDraft((prev) => [...prev, slot]);
    setOpenSlotId(slot.id);
    setShowKindPicker(false);
  }
  function save() {
    const next = writeInputSlots(agent.model_params, draft);
    update.mutate({ agentId: agent.id, body: { model_params: next } });
  }
  function reset() {
    setDraft(serverSlots);
  }

  return (
    <section className={styles.section}>
      <header className={styles.head}>
        <span className={styles.title}>
          Input slots ({draft.length})
        </span>
        <button
          type="button"
          className={styles.add}
          onClick={() => setShowKindPicker((v) => !v)}
          aria-expanded={showKindPicker}
        >
          + Add input
        </button>
      </header>

      {showKindPicker && (
        <div className={styles.kindPicker}>
          {INPUT_SLOT_KINDS.map((k) => (
            <button
              key={k}
              type="button"
              className={styles.kindBtn}
              onClick={() => addSlot(k)}
            >
              <span className={styles.kindBtnLabel}>
                {INPUT_SLOT_KIND_LABEL[k]}
              </span>
              <span className={styles.kindBtnDesc}>
                {INPUT_SLOT_KIND_DESCRIPTION[k]}
              </span>
            </button>
          ))}
        </div>
      )}

      {draft.length === 0 && !showKindPicker && (
        <div className={styles.empty}>
          No input slots. Click <strong>+ Add input</strong> to attach a
          source, system prompt, prompt guide, or LoRA scope to this
          agent.
        </div>
      )}

      <div className={styles.list}>
        {draft.map((slot) => {
          const expanded = openSlotId === slot.id;
          return (
            <div key={slot.id} className={styles.slot}>
              <button
                type="button"
                className={styles.slotHead}
                onClick={() => setOpenSlotId(expanded ? null : slot.id)}
                data-kind={slot.kind}
              >
                <span className={styles.slotKind}>
                  {INPUT_SLOT_KIND_LABEL[slot.kind]}
                </span>
                <span className={styles.slotLabel}>{slot.label}</span>
                <SlotSummary slot={slot} />
                <span className={styles.slotChev}>{expanded ? "▾" : "▸"}</span>
              </button>
              {expanded && (
                <SlotEditor
                  slot={slot}
                  onPatch={(patch) => patchSlot(slot.id, patch)}
                  onDelete={() => deleteSlot(slot.id)}
                />
              )}
            </div>
          );
        })}
      </div>

      {(dirty || update.isPending || update.isError) && (
        <div className={styles.saveBar}>
          <button
            type="button"
            className={styles.saveBtn}
            disabled={!dirty || update.isPending}
            onClick={save}
          >
            {update.isPending ? "Saving…" : "Save inputs"}
          </button>
          {dirty && !update.isPending && (
            <button type="button" className={styles.resetBtn} onClick={reset}>
              Reset
            </button>
          )}
          {update.isError && (
            <span className={styles.saveErr}>
              {(update.error as Error).message}
            </span>
          )}
        </div>
      )}
    </section>
  );
}

// --- per-slot summary line ---------------------------------------------

function SlotSummary({ slot }: { slot: AgentInputSlot }) {
  let text = "";
  switch (slot.kind) {
    case "source": {
      const cfg = slot.source!;
      const bits = [
        cfg.source_slot_id ? "slot bound" : "no slot",
        cfg.vl_model ?? "no VL model",
      ];
      text = bits.join(" · ");
      break;
    }
    case "prompt_guide": {
      const cfg = slot.prompt_guide!;
      const guide = cfg.guide_id ?? "(no guide)";
      const gen = cfg.generation_type ?? "(infer)";
      text = `${guide} · ${gen}`;
      break;
    }
    case "system": {
      const text_ = slot.system!.text.trim();
      text = text_ ? `${text_.length} chars` : "empty";
      break;
    }
    case "loras": {
      const cfg = slot.loras!;
      const counts = [];
      if (cfg.list.length) counts.push(`${cfg.list.length} entries`);
      if (cfg.filters.length) counts.push(`${cfg.filters.length} filters`);
      text = `${cfg.mode}${counts.length ? " · " + counts.join(" · ") : ""}`;
      break;
    }
  }
  return <span className={styles.slotSummary}>{text}</span>;
}

// --- per-kind editor forms ---------------------------------------------

function SlotEditor({
  slot,
  onPatch,
  onDelete,
}: {
  slot: AgentInputSlot;
  onPatch: (patch: Partial<AgentInputSlot>) => void;
  onDelete: () => void;
}) {
  return (
    <div className={styles.form}>
      <label className={styles.field}>
        <span>label</span>
        <input
          className={styles.input}
          value={slot.label}
          onChange={(e) => onPatch({ label: e.currentTarget.value })}
          spellCheck={false}
        />
      </label>

      {slot.kind === "source" && (
        <SourceForm slot={slot} onPatch={onPatch} />
      )}
      {slot.kind === "prompt_guide" && (
        <PromptGuideForm slot={slot} onPatch={onPatch} />
      )}
      {slot.kind === "system" && (
        <SystemForm slot={slot} onPatch={onPatch} />
      )}
      {slot.kind === "loras" && (
        <LorasForm slot={slot} onPatch={onPatch} />
      )}

      <label className={styles.field}>
        <span>description</span>
        <textarea
          className={styles.input}
          rows={2}
          value={slot.description ?? ""}
          onChange={(e) =>
            onPatch({ description: e.currentTarget.value || null })
          }
          placeholder="Optional note for yourself or the LLM"
        />
      </label>

      <div className={styles.formActions}>
        <button type="button" className={styles.delete} onClick={onDelete}>
          Remove input
        </button>
      </div>
    </div>
  );
}

function SourceForm({
  slot,
  onPatch,
}: {
  slot: AgentInputSlot;
  onPatch: (patch: Partial<AgentInputSlot>) => void;
}) {
  const { session, sourceSlots } = useComfy();
  const models = useLmModels();
  const cfg = slot.source!;
  const visionModels = (models.data ?? []).filter(
    (m) => m.vision && !m.hidden && m.enabled,
  );

  function patch(p: Partial<typeof cfg>) {
    onPatch({ source: { ...cfg, ...p } });
  }

  // Resolve the bound slot → image (for the helper line below the
  // dropdown). The slot may be deleted out from under us; render a
  // small warning in that case.
  const boundSlot =
    sourceSlots.find((s) => s.id === cfg.source_slot_id) ?? null;
  const boundImage = boundSlot
    ? session.source_images.find((i) => i.id === boundSlot.source_image_id) ?? null
    : null;

  return (
    <>
      <label className={styles.field}>
        <span>source slot</span>
        <select
          className={styles.input}
          value={cfg.source_slot_id ?? ""}
          onChange={(e) =>
            patch({ source_slot_id: e.currentTarget.value || null })
          }
        >
          <option value="">(no slot)</option>
          {sourceSlots.map((s) => (
            <option key={s.id} value={s.id}>
              {s.key} — {s.purpose}
              {s.source_image_id ? " · image bound" : " · unbound"}
            </option>
          ))}
        </select>
        {sourceSlots.length === 0 && (
          <span className={styles.fieldHint}>
            No source slots yet. Open the Sources panel and create one
            (Main / Scene reference / Text-only reference).
          </span>
        )}
        {cfg.source_slot_id && !boundSlot && (
          <span className={styles.fieldHint} style={{ color: "var(--danger)" }}>
            Slot was deleted. Pick another or clear.
          </span>
        )}
        {boundSlot && !boundImage && (
          <span className={styles.fieldHint}>
            Slot <code>{boundSlot.key}</code> is unbound — bind an image
            to it in the Sources panel before this agent can run.
          </span>
        )}
        {boundImage && (
          <span className={styles.fieldHint}>
            Resolves to <code>{boundImage.original_filename}</code>.
          </span>
        )}
      </label>

      <label className={styles.field}>
        <span>VL model</span>
        <select
          className={styles.input}
          value={cfg.vl_model ?? ""}
          onChange={(e) =>
            patch({ vl_model: e.currentTarget.value || null })
          }
        >
          <option value="">{models.isLoading ? "Loading…" : "(none)"}</option>
          {visionModels.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
        {visionModels.length === 0 && !models.isLoading && (
          <span className={styles.fieldHint}>
            No vision-capable models registered. Mark a model as
            "vision" in Settings → LMStudio.
          </span>
        )}
      </label>

      <label className={styles.field}>
        <span>VL prompt</span>
        <textarea
          className={styles.input}
          rows={3}
          value={cfg.vl_prompt}
          onChange={(e) => patch({ vl_prompt: e.currentTarget.value })}
        />
      </label>

      <label className={styles.field}>
        <span>VL temp.</span>
        <input
          type="number"
          className={styles.numInput}
          step={0.05}
          min={0}
          max={2}
          value={cfg.vl_temperature ?? ""}
          placeholder="0.3"
          onChange={(e) => {
            const n = parseFloat(e.currentTarget.value);
            patch({ vl_temperature: Number.isNaN(n) ? null : n });
          }}
        />
      </label>

      <label className={styles.field}>
        <span>VL max tok.</span>
        <input
          type="number"
          className={styles.numInput}
          step={64}
          min={32}
          max={8192}
          value={cfg.vl_max_tokens ?? ""}
          placeholder="512"
          onChange={(e) => {
            const n = parseInt(e.currentTarget.value, 10);
            patch({ vl_max_tokens: Number.isNaN(n) ? null : n });
          }}
        />
      </label>
    </>
  );
}

function PromptGuideForm({
  slot,
  onPatch,
}: {
  slot: AgentInputSlot;
  onPatch: (patch: Partial<AgentInputSlot>) => void;
}) {
  const cfg = slot.prompt_guide!;
  const [search, setSearch] = useState("");
  // The library list filters server-side via `q`; we pass the user's
  // search through directly. Empty string returns the full list.
  const families = useFamilies(search.trim());
  const visibleFamilies = (families.data ?? []).filter((f) => !f.hidden);
  const selectedFamily =
    cfg.guide_id != null
      ? visibleFamilies.find((f) => f.id === cfg.guide_id) ?? null
      : null;

  function patch(p: Partial<typeof cfg>) {
    onPatch({ prompt_guide: { ...cfg, ...p } });
  }

  return (
    <>
      <label className={styles.field}>
        <span>generation</span>
        <select
          className={styles.input}
          value={cfg.generation_type ?? ""}
          onChange={(e) => {
            const v = e.currentTarget.value;
            patch({
              generation_type:
                v === "i2i" || v === "t2i"
                  ? (v as PromptGuideGenerationType)
                  : null,
            });
          }}
        >
          <option value="">(infer from workflow)</option>
          {GENERATION_TYPES.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.field}>
        <span>search</span>
        <input
          className={styles.input}
          type="search"
          value={search}
          placeholder="Filter families by id or display name…"
          onChange={(e) => setSearch(e.currentTarget.value)}
        />
      </label>

      <label className={styles.field}>
        <span>guide</span>
        <select
          className={styles.input}
          value={cfg.guide_id ?? ""}
          onChange={(e) =>
            patch({ guide_id: e.currentTarget.value || null })
          }
        >
          <option value="">
            {families.isLoading ? "Loading…" : "(pick a family)"}
          </option>
          {visibleFamilies.map((f) => (
            <option key={f.id} value={f.id}>
              {f.display_name} — {f.id}
            </option>
          ))}
          {/* Keep the current pick visible even if it's been hidden or
              filtered out so the user can see what's bound. */}
          {cfg.guide_id != null && !selectedFamily && (
            <option value={cfg.guide_id}>{cfg.guide_id} (not in list)</option>
          )}
        </select>
        {!families.isLoading && visibleFamilies.length === 0 && (
          <span className={styles.fieldHint}>
            {search.trim()
              ? "No families match the filter."
              : "No families in the library yet — add one in Library → Families."}
          </span>
        )}
        {selectedFamily && (
          <span className={styles.fieldHint}>
            Composes the family's base prompt guide
            {cfg.generation_type
              ? ` plus its prompt_${cfg.generation_type} section`
              : " (pick a generation type to add the mode-specific section)"}
            .
          </span>
        )}
      </label>
    </>
  );
}

function SystemForm({
  slot,
  onPatch,
}: {
  slot: AgentInputSlot;
  onPatch: (patch: Partial<AgentInputSlot>) => void;
}) {
  const cfg = slot.system!;
  return (
    <label className={styles.field}>
      <span>extra system</span>
      <textarea
        className={styles.input}
        rows={5}
        value={cfg.text}
        onChange={(e) =>
          onPatch({ system: { ...cfg, text: e.currentTarget.value } })
        }
        placeholder="This text is appended to the agent's mandatory system prompt."
      />
    </label>
  );
}

function LorasForm({
  slot,
  onPatch,
}: {
  slot: AgentInputSlot;
  onPatch: (patch: Partial<AgentInputSlot>) => void;
}) {
  const cfg = slot.loras!;
  function patch(p: Partial<typeof cfg>) {
    onPatch({ loras: { ...cfg, ...p } });
  }
  const [draftEntry, setDraftEntry] = useState("");
  const [draftFilterField, setDraftFilterField] =
    useState<LoraFilter["field"]>("tag");
  const [draftFilterMatch, setDraftFilterMatch] = useState("");

  return (
    <>
      <div className={styles.field}>
        <span>mode</span>
        <div className={styles.modeRow}>
          <label className={styles.radio}>
            <input
              type="radio"
              checked={cfg.mode === "allow"}
              onChange={() => patch({ mode: "allow" })}
            />
            Allow — only entries / filters below
          </label>
          <label className={styles.radio}>
            <input
              type="radio"
              checked={cfg.mode === "deny"}
              onChange={() => patch({ mode: "deny" })}
            />
            Deny — block entries / filters below
          </label>
        </div>
      </div>

      <label className={styles.field}>
        <span>family</span>
        <select
          className={styles.input}
          value={cfg.model_family ?? ""}
          onChange={(e) =>
            patch({ model_family: e.currentTarget.value || null })
          }
        >
          <option value="">(any)</option>
          {MOCK_MODEL_FAMILIES.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </label>

      <div className={styles.field}>
        <span>list</span>
        <div className={styles.listInline}>
          {cfg.list.length === 0 && (
            <span className={styles.dim}>no entries</span>
          )}
          {cfg.list.map((entry, idx) => (
            <span key={`${entry}-${idx}`} className={styles.chip}>
              {entry}
              <button
                type="button"
                className={styles.chipDel}
                onClick={() =>
                  patch({ list: cfg.list.filter((_, i) => i !== idx) })
                }
                aria-label={`Remove ${entry}`}
              >
                ×
              </button>
            </span>
          ))}
          <input
            className={styles.chipInput}
            value={draftEntry}
            placeholder="lora name… (Enter)"
            onChange={(e) => setDraftEntry(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draftEntry.trim()) {
                e.preventDefault();
                patch({ list: [...cfg.list, draftEntry.trim()] });
                setDraftEntry("");
              }
            }}
          />
        </div>
      </div>

      <div className={styles.field}>
        <span>filters</span>
        <div className={styles.filtersBox}>
          {cfg.filters.length === 0 && (
            <span className={styles.dim}>no filters</span>
          )}
          {cfg.filters.map((f, idx) => (
            <div key={idx} className={styles.filterRow}>
              <span className={styles.filterField}>{f.field}</span>
              <span className={styles.filterMatch}>{f.match}</span>
              <button
                type="button"
                className={styles.chipDel}
                onClick={() =>
                  patch({ filters: cfg.filters.filter((_, i) => i !== idx) })
                }
                aria-label="Remove filter"
              >
                ×
              </button>
            </div>
          ))}
          <div className={styles.filterAdd}>
            <select
              className={styles.input}
              value={draftFilterField}
              onChange={(e) =>
                setDraftFilterField(
                  e.currentTarget.value as LoraFilter["field"],
                )
              }
            >
              {MOCK_LORA_FILTER_FIELDS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
            <input
              className={styles.input}
              value={draftFilterMatch}
              placeholder="match…"
              onChange={(e) => setDraftFilterMatch(e.currentTarget.value)}
            />
            <button
              type="button"
              className={styles.add}
              disabled={!draftFilterMatch.trim()}
              onClick={() => {
                patch({
                  filters: [
                    ...cfg.filters,
                    {
                      field: draftFilterField,
                      match: draftFilterMatch.trim(),
                    },
                  ],
                });
                setDraftFilterMatch("");
              }}
            >
              + filter
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
