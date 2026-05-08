/** Output-slots editor for one agent.
 *
 *  Lets the user add/remove/rebind agent output slots. Each slot has
 *  three flavours:
 *
 *  - **auto** — kind + description snapshot from the workflow slot at
 *    bind time. Unbound auto slots are allowed but useless until
 *    bound; the user can pick from any binding=llm workflow slot not
 *    already taken by another agent.
 *  - **custom** — fully user-defined: label + kind chosen here. Can
 *    bind to a compatible workflow slot or stay unbound.
 *  - **preset** — `positive` / `negative`, fixed kind, only created
 *    via the seed_default endpoint (kept here read-only for parity).
 *
 *  The single-bind rule (one workflow slot ↦ at most one agent slot
 *  across the whole session) is enforced both within the local draft
 *  and against sibling agents. See docs/comfy-agents-ui-mock-plan.md.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ALLOWED_BINDINGS,
  SLOT_KINDS,
  SLOT_KIND_LABEL,
  useUpdateAgent,
  type Agent,
  type AgentOutputSlot,
  type SlotKind,
} from "@/api/comfy";
import { useComfy } from "../state/useComfy";
import { readInputSlots } from "./agent-input-slots";
import { OutputSlotRow } from "./OutputSlotRow";
import styles from "./AgentSlotsEditor.module.css";

/** Build the kind picker for an agent's custom output slot.
 *
 *  Strings / numbers / booleans / enums are always available — an LLM
 *  call produces those natively. `lora_name` is conditional: an agent
 *  can output a LoRA name only when it's been given a LoRAs input
 *  slot to draw from (the input slot scopes the allowed pool, the
 *  agent picks from it). Image kinds and `checkpoint_name` stay out
 *  entirely — those are filled by other bindings.
 */
function computeKindOptions(hasLorasInput: boolean): SlotKind[] {
  return SLOT_KINDS.filter((k) => {
    if (!ALLOWED_BINDINGS[k].includes("llm")) return false;
    if (k === "lora_name" && !hasLorasInput) return false;
    return true;
  });
}

export function AgentSlotsEditor({ agent }: { agent: Agent }) {
  const { session, slotMap, agents } = useComfy();
  const update = useUpdateAgent(session.id);

  const [draft, setDraft] = useState<AgentOutputSlot[]>(agent.output_slots);
  const [openSlotId, setOpenSlotId] = useState<string | null>(null);

  const dirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(agent.output_slots),
    [draft, agent.output_slots],
  );

  // Reconcile the local draft with the upstream agent row whenever it
  // changes. Two cases:
  //
  // 1. The user has no unsaved structural edits — the draft and the
  //    server snapshot match structurally (everything bar
  //    `last_value`). Adopt the server snapshot wholesale; this is
  //    what surfaces /run output: the runner writes new
  //    `last_value`s onto the agent, the agents query updates, this
  //    effect fires and the new values land in the UI.
  //
  // 2. The user has structural edits in flight (renamed a slot,
  //    changed a binding, …). Keep their structural draft, but pull
  //    fresh `last_value`s from the server for matching slot ids so a
  //    /run that lands mid-edit still shows. Slots the user has
  //    deleted locally stay deleted; slots they've added locally have
  //    no server peer and keep their (null) `last_value`.
  //
  // We deliberately depend ONLY on the server snapshot. Adding
  // `draft` would re-run on every keystroke.
  useEffect(() => {
    setDraft((prev) => {
      if (
        JSON.stringify(structuralOnly(prev)) ===
        JSON.stringify(structuralOnly(agent.output_slots))
      ) {
        return agent.output_slots;
      }
      const byId = new Map(agent.output_slots.map((s) => [s.id, s]));
      return prev.map((s) => {
        const server = byId.get(s.id);
        if (!server) return s;
        return { ...s, last_value: server.last_value };
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent.output_slots]);

  // Workflow slots eligible for binding (binding=llm).
  const llmWorkflowSlots = useMemo(
    () => slotMap?.slot_map.slots.filter((s) => s.binding === "llm") ?? [],
    [slotMap],
  );

  // The kind picker for new custom slots is dynamic: lora_name only
  // shows up when the agent has a LoRAs input slot to draw names
  // from. (See computeKindOptions for the full rule.)
  const kindOptions = useMemo(() => {
    const inputSlots = readInputSlots(agent.model_params);
    const hasLorasInput = inputSlots.some((s) => s.kind === "loras");
    return computeKindOptions(hasLorasInput);
  }, [agent.model_params]);

  // Labels already taken by *other* agents in this session — those
  // become disabled options in this editor's binding pickers. The
  // current agent's own bindings are still selectable so the user can
  // re-pick the same target after a rename.
  const lockedLabels = useMemo(() => {
    const set = new Set<string>();
    for (const a of agents) {
      if (a.id === agent.id) continue;
      for (const s of a.output_slots) {
        if (s.bound_to?.workflow_slot_label) {
          set.add(s.bound_to.workflow_slot_label);
        }
      }
    }
    return set;
  }, [agents, agent.id]);

  // Labels already taken by *this draft's* slots — in-draft
  // self-conflict detection.
  const draftLabels = useMemo(() => {
    const counts = new Map<string, number>();
    for (const s of draft) {
      const t = s.bound_to?.workflow_slot_label;
      if (t) counts.set(t, (counts.get(t) ?? 0) + 1);
    }
    return counts;
  }, [draft]);

  function patchSlot(id: string, patch: Partial<AgentOutputSlot>) {
    setDraft((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...patch } : s)),
    );
  }
  function deleteSlot(id: string) {
    setDraft((prev) => prev.filter((s) => s.id !== id));
    if (openSlotId === id) setOpenSlotId(null);
  }
  function addAutoSlot() {
    // 16 hex chars — short enough for the backend's 32-char id ceiling
    // and unique enough for sessions of <1k slots.
    const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    const label = uniqueLabel("output", draft);
    const slot: AgentOutputSlot = {
      id,
      origin: "auto",
      preset: null,
      kind: null,
      label,
      description: null,
      last_value: null,
      bound_to: null,
    };
    setDraft((prev) => [...prev, slot]);
    setOpenSlotId(id);
  }
  function addCustomSlot() {
    // 16 hex chars — short enough for the backend's 32-char id ceiling
    // and unique enough for sessions of <1k slots.
    const id = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    const label = uniqueLabel("custom", draft);
    const slot: AgentOutputSlot = {
      id,
      origin: "custom",
      preset: null,
      kind: "text",
      label,
      description: null,
      last_value: null,
      bound_to: null,
    };
    setDraft((prev) => [...prev, slot]);
    setOpenSlotId(id);
  }

  function save() {
    // Use .mutate (fire-and-forget) instead of .mutateAsync — the
    // mutation's error is already surfaced via `update.isError` in the
    // save bar, so awaiting only adds noise (uncaught rejections in
    // the console when the backend 422s a draft).
    update.mutate({ agentId: agent.id, body: { output_slots: draft } });
  }
  function reset() {
    setDraft(agent.output_slots);
  }

  // Is this draft ready to save? (Validations the backend would also
  // catch, surfaced inline so the Save button can be disabled.)
  const validation = useMemo(
    () => validateDraft(draft, lockedLabels, llmWorkflowSlots),
    [draft, lockedLabels, llmWorkflowSlots],
  );

  return (
    <div className={styles.editor}>
      <div className={styles.header}>
        <span className={styles.title}>
          Output slots ({draft.length})
        </span>
        <div className={styles.headerBtns}>
          <button
            type="button"
            className={styles.add}
            onClick={addAutoSlot}
            title="Add an auto slot — kind is filled when you bind it"
          >
            + auto
          </button>
          <button
            type="button"
            className={styles.add}
            onClick={addCustomSlot}
            title="Add a custom slot — pick the kind manually"
          >
            + custom
          </button>
        </div>
      </div>

      {draft.length === 0 && (
        <div className={styles.empty}>
          No output slots yet. Add one above (auto for a workflow-bound
          slot, custom for a free-form one).
        </div>
      )}

      <div className={styles.list}>
        {draft.map((slot) => {
          const expanded = openSlotId === slot.id;
          const error = validation.bySlotId.get(slot.id) ?? null;
          return (
            <div
              key={slot.id}
              className={`${styles.slotItem} ${error ? styles.slotItemError : ""}`}
            >
              <div
                className={styles.slotPreview}
                onClick={() =>
                  setOpenSlotId(expanded ? null : slot.id)
                }
              >
                <OutputSlotRow slot={slot} />
              </div>
              {expanded && (
                <SlotEditor
                  slot={slot}
                  llmSlots={llmWorkflowSlots}
                  lockedLabels={lockedLabels}
                  draftCounts={draftLabels}
                  onPatch={(patch) => patchSlot(slot.id, patch)}
                  onDelete={() => deleteSlot(slot.id)}
                  kindOptions={kindOptions}
                />
              )}
              {error && (
                <div className={styles.errorRow} role="alert">
                  {error}
                </div>
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
            disabled={!dirty || !validation.ok || update.isPending}
            onClick={save}
            title={
              !validation.ok
                ? validation.firstError ?? "Fix errors before saving"
                : ""
            }
          >
            {update.isPending ? "Saving…" : "Save slots"}
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
    </div>
  );
}

// --- per-slot editor ----------------------------------------------------

function SlotEditor({
  slot,
  llmSlots,
  lockedLabels,
  draftCounts,
  onPatch,
  onDelete,
  kindOptions,
}: {
  slot: AgentOutputSlot;
  llmSlots: import("@/api/comfy").SlotDefinition[];
  lockedLabels: Set<string>;
  draftCounts: Map<string, number>;
  onPatch: (patch: Partial<AgentOutputSlot>) => void;
  onDelete: () => void;
  kindOptions: SlotKind[];
}) {
  const isAuto = slot.origin === "auto";
  const isCustom = slot.origin === "custom";
  const isPreset = slot.origin === "preset";

  const currentTarget = slot.bound_to?.workflow_slot_label ?? "";

  return (
    <div className={styles.slotForm}>
      <label className={styles.field}>
        <span>label</span>
        <input
          className={styles.input}
          value={slot.label}
          onChange={(e) => onPatch({ label: e.currentTarget.value })}
          spellCheck={false}
        />
      </label>

      <label className={styles.field}>
        <span>kind</span>
        {isCustom ? (
          <select
            className={styles.input}
            value={slot.kind ?? "text"}
            onChange={(e) =>
              onPatch({ kind: e.currentTarget.value as SlotKind })
            }
          >
            {kindOptions.map((k) => (
              <option key={k} value={k}>
                {SLOT_KIND_LABEL[k]}
              </option>
            ))}
          </select>
        ) : (
          <span className={styles.readonlyChip}>
            {slot.kind ? SLOT_KIND_LABEL[slot.kind] : "(picked at bind)"}
          </span>
        )}
      </label>

      <label className={styles.field}>
        <span>binds to</span>
        <select
          className={styles.input}
          value={currentTarget}
          onChange={(e) => {
            const next = e.currentTarget.value;
            if (next === "") {
              onPatch({ bound_to: null });
            } else {
              const ws = llmSlots.find((s) => s.label === next);
              const patch: Partial<AgentOutputSlot> = {
                bound_to: { workflow_slot_label: next },
              };
              if (isAuto && slot.kind == null && ws) patch.kind = ws.kind;
              onPatch(patch);
            }
          }}
        >
          <option value="">(unbound)</option>
          {llmSlots
            // Custom slots are only compatible with workflow slots of
            // the same kind. Auto slots accept any kind (the bind
            // resolves the kind for them). Hide incompatibles entirely
            // rather than greying them out — users found the disabled
            // rows noisy when most of the list was incompatible.
            .filter(
              (ws) => !(isCustom && slot.kind != null && ws.kind !== slot.kind),
            )
            .map((ws) => {
              const taken = lockedLabels.has(ws.label);
              const dupInDraft =
                (draftCounts.get(ws.label) ?? 0) > 1 &&
                currentTarget !== ws.label;
              const note = taken
                ? " — taken by another agent"
                : dupInDraft
                  ? " — already used in this agent"
                  : "";
              return (
                <option key={ws.label} value={ws.label} disabled={taken}>
                  {ws.label} ({ws.kind}){note}
                </option>
              );
            })}
        </select>
      </label>

      <label className={styles.field}>
        <span>description</span>
        <textarea
          className={styles.input}
          rows={2}
          value={slot.description ?? ""}
          onChange={(e) =>
            onPatch({ description: e.currentTarget.value || null })
          }
          placeholder={
            isAuto
              ? "Auto slots get description from the workflow + catalog at bind time"
              : "Hint for the LLM about what value this slot should hold"
          }
        />
      </label>

      <div className={styles.formActions}>
        <button
          type="button"
          className={styles.delete}
          onClick={onDelete}
          disabled={isPreset}
          title={isPreset ? "Preset slots are managed by the seed action" : "Remove this slot"}
        >
          Remove slot
        </button>
      </div>
    </div>
  );
}

// --- helpers ------------------------------------------------------------

/** Strip the per-slot `last_value` so we can compare two slot lists
 *  on structural fields alone. `last_value` is an output of the
 *  agent's `/run`, not something the user edits in this panel — it
 *  must not block the re-sync from server when it's the only diff. */
function structuralOnly(
  slots: AgentOutputSlot[],
): Omit<AgentOutputSlot, "last_value">[] {
  return slots.map(({ last_value: _drop, ...rest }) => {
    void _drop;
    return rest;
  });
}

function uniqueLabel(base: string, existing: AgentOutputSlot[]): string {
  const taken = new Set(existing.map((s) => s.label));
  let label = base;
  let n = 2;
  while (taken.has(label)) label = `${base}_${n++}`;
  return label;
}

type DraftValidation = {
  ok: boolean;
  bySlotId: Map<string, string>;
  firstError: string | null;
};

function validateDraft(
  draft: AgentOutputSlot[],
  lockedLabels: Set<string>,
  llmSlots: import("@/api/comfy").SlotDefinition[],
): DraftValidation {
  const bySlotId = new Map<string, string>();
  const seenLabels = new Map<string, string>(); // label → first slot id
  const seenTargets = new Map<string, string>(); // target → first slot id
  const llmByLabel = new Map(llmSlots.map((s) => [s.label, s]));
  for (const slot of draft) {
    if (!slot.label.trim()) {
      bySlotId.set(slot.id, "Label is required");
      continue;
    }
    const labelOwner = seenLabels.get(slot.label);
    if (labelOwner && labelOwner !== slot.id) {
      bySlotId.set(slot.id, `Duplicate label "${slot.label}" within this agent`);
      continue;
    }
    seenLabels.set(slot.label, slot.id);

    if (slot.origin === "custom" && slot.kind == null) {
      bySlotId.set(slot.id, "Custom slots need a kind");
      continue;
    }

    const target = slot.bound_to?.workflow_slot_label;
    if (target) {
      if (lockedLabels.has(target)) {
        bySlotId.set(slot.id, `"${target}" is bound by another agent`);
        continue;
      }
      const owner = seenTargets.get(target);
      if (owner && owner !== slot.id) {
        bySlotId.set(slot.id, `"${target}" is already bound by another slot in this agent`);
        continue;
      }
      seenTargets.set(target, slot.id);

      const ws = llmByLabel.get(target);
      if (!ws) {
        bySlotId.set(slot.id, `Workflow slot "${target}" no longer exists`);
        continue;
      }
      if (slot.kind != null && ws.kind !== slot.kind) {
        bySlotId.set(
          slot.id,
          `Kind mismatch: slot is ${slot.kind}, workflow expects ${ws.kind}`,
        );
        continue;
      }
    }
  }
  let firstError: string | null = null;
  for (const v of bySlotId.values()) {
    firstError = v;
    break;
  }
  return { ok: bySlotId.size === 0, bySlotId, firstError };
}
