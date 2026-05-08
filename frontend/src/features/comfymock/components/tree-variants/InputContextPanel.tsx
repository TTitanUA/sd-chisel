/** Right-hand editor pane (col 3) shared by every d-tree-* variant.
 *
 *  Whatever the user has clicked / focused in the centre tree shows
 *  up here as a slot editor — this is the "drawer" experience but
 *  permanently visible so the variants share a 3-col layout.
 *
 *  Three states:
 *  - **no active**: friendly placeholder, no form.
 *  - **active + mapped**: edit the slot (label, kind, binding, frozen
 *    value or source-slot reference, agent+output for llm,
 *    description) + Unmap.
 *  - **active + unmapped + candidate**: pick a binding and click to
 *    create the slot.
 *
 *  The agent+output picker for `binding=llm` mutates the *agents*
 *  store rather than the slot draft — agent output_slots are the
 *  canonical place where the binding lives, and the workflow slot
 *  itself only declares "an LLM fills me" via its binding field.
 *  Picking a new agent/output also clears any previous binding to
 *  the same workflow slot label, enforcing the single-bind rule
 *  client-side ahead of the server validation.
 *
 *  See docs/comfy-agents-ui-mock-plan.md.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ALLOWED_BINDINGS,
  SLOT_BINDING_LABEL,
  SLOT_KIND_LABEL,
  useUpdateAgent,
  type Agent,
  type AgentOutputSlot,
  type CandidateInput,
  type SlotBinding,
  type SlotDefinition,
  type SlotKind,
} from "@/api/comfy";
import { useComfyMock } from "../../state/useComfyMock";
import {
  compatibleOutputsFor,
  slotFromCandidate,
  type CompatibleOutput,
} from "../slot-variants/slot-helpers";
import type { SlotDraftHelpers } from "../slot-variants/useSlotDraft";
import { formatValue, type MappingInputRow, type MappingNodeRow } from "./tree-helpers";
import styles from "./MappingTreeShell.module.css";

export type ActiveInput = { nodeId: string; inputName: string };

export function InputContextPanel({
  active,
  rows,
  helpers,
}: {
  active: ActiveInput | null;
  rows: MappingNodeRow[];
  helpers: SlotDraftHelpers;
}) {
  const activeRow = useMemo(() => {
    if (!active) return null;
    for (const node of rows) {
      if (node.nodeId !== active.nodeId) continue;
      const input = node.inputs.find((i) => i.name === active.inputName);
      if (input) return { node, input };
    }
    return null;
  }, [active, rows]);

  if (!active) {
    return (
      <div className={styles.editorEmpty}>
        Click an input in the tree to edit its slot here.
      </div>
    );
  }
  if (!activeRow) {
    return (
      <div className={styles.editorEmpty}>
        That input is no longer in the workflow.
      </div>
    );
  }

  const { input } = activeRow;
  return (
    <div className={styles.editorBody}>
      <div className={styles.editorIntro}>
        <span className={styles.editorLocator}>
          <code>#{active.nodeId}</code> · <code>{active.inputName}</code>
        </span>
        {input.candidate && (
          <span className={styles.editorKindBadge}>
            {SLOT_KIND_LABEL[input.candidate.kind]}
          </span>
        )}
        <ValueSummary input={input} />
      </div>
      {input.mappedSlot ? (
        <EditMapped helpers={helpers} input={input} />
      ) : input.candidate ? (
        <CreateForm helpers={helpers} candidate={input.candidate} />
      ) : (
        <em className={styles.editorEmpty}>
          Not mappable — wired or unsupported type.
        </em>
      )}
    </div>
  );
}

// --- Read-only value summary -------------------------------------

/** Render the input's *current* value (from the workflow graph) and,
 *  when present, the *default* value from the node schema. Single
 *  line, truncated. Kept under the locator chip in the editor intro. */
function ValueSummary({ input }: { input: MappingInputRow }) {
  const def = candidateDefault(input.candidate);
  return (
    <>
      <span className={styles.fieldHint}>
        Current: <code>{formatValue(input.rawValue)}</code>
      </span>
      {def !== undefined && (
        <span className={styles.fieldHint}>
          Default: <code>{formatValue(def)}</code>
        </span>
      )}
    </>
  );
}

function candidateDefault(c: CandidateInput | null): unknown | undefined {
  if (!c) return undefined;
  const md = (c.metadata ?? {}) as Record<string, unknown>;
  if ("default" in md) return md.default;
  return undefined;
}

// --- Create form (unmapped + candidate) ---------------------------

function CreateForm({
  helpers,
  candidate,
}: {
  helpers: SlotDraftHelpers;
  candidate: CandidateInput;
}) {
  const allowed = ALLOWED_BINDINGS[candidate.kind].filter(
    (b) => b !== "library_loras",
  );
  return (
    <>
      <span className={styles.fieldHint}>
        This input isn't mapped yet. Pick a binding to create the slot —
        you can refine the label and value below afterwards.
      </span>
      {allowed.map((b) => (
        <button
          key={b}
          type="button"
          className={styles.primary}
          onClick={() =>
            helpers.appendSlot(slotFromCandidate(candidate, helpers.draft ?? [], b))
          }
        >
          + Map as {SLOT_BINDING_LABEL[b]}
        </button>
      ))}
    </>
  );
}

// --- Edit form (mapped) -------------------------------------------

function EditMapped({
  helpers,
  input,
}: {
  helpers: SlotDraftHelpers;
  input: MappingInputRow;
}) {
  const { sourceSlots, session, agents } = useComfyMock();
  const updateAgent = useUpdateAgent(session.id);
  const index = input.mappedIndex!;
  const slot = helpers.draft?.[index];
  if (!slot) return null;
  const allowed = ALLOWED_BINDINGS[slot.kind].filter(
    (b) => b !== "library_loras",
  );
  const meta = (slot.metadata ?? {}) as Record<string, unknown>;
  const frozenValue = meta.value;
  const sourceSlotId =
    typeof meta.source_slot_id === "string" ? meta.source_slot_id : "";
  const def = candidateDefault(input.candidate);
  // Default is "available" when present and not equal to the current
  // frozen value — otherwise the reset button is a no-op and we hide
  // it to keep the form quiet.
  const canResetToDefault =
    slot.binding === "frozen" &&
    def !== undefined &&
    !shallowEqual(def, frozenValue);

  return (
    <>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>Label</span>
        <input
          className={styles.input}
          value={slot.label}
          onChange={(e) => helpers.patchSlot(index, { label: e.currentTarget.value })}
          spellCheck={false}
        />
      </label>

      <label className={styles.field}>
        <span className={styles.fieldLabel}>Binding</span>
        <select
          className={styles.input}
          value={slot.binding}
          onChange={(e) =>
            helpers.setBinding(index, e.currentTarget.value as SlotBinding)
          }
        >
          {allowed.map((b) => (
            <option key={b} value={b}>
              {SLOT_BINDING_LABEL[b]}
            </option>
          ))}
        </select>
      </label>

      {slot.binding === "frozen" && (
        <>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Frozen value</span>
            <input
              className={styles.input}
              value={
                typeof frozenValue === "string"
                  ? frozenValue
                  : frozenValue == null
                    ? ""
                    : String(frozenValue)
              }
              onChange={(e) => helpers.setFrozenValue(index, e.currentTarget.value)}
            />
          </label>
          {canResetToDefault && (
            <button
              type="button"
              className={styles.primary}
              onClick={() => helpers.setFrozenValue(index, def)}
              title={`Reset frozen value to ${formatValue(def)}`}
            >
              Reset to default ({formatValue(def)})
            </button>
          )}
        </>
      )}

      {slot.binding === "user_image" && (
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Source slot</span>
          <select
            className={styles.input}
            value={sourceSlotId}
            onChange={(e) => {
              const next = e.currentTarget.value || null;
              const restMeta = { ...meta };
              if (next) restMeta.source_slot_id = next;
              else delete restMeta.source_slot_id;
              helpers.patchSlot(index, { metadata: restMeta });
            }}
          >
            <option value="">(unbound — Generate will fail)</option>
            {sourceSlots.map((s) => (
              <option key={s.id} value={s.id}>
                {s.key} — {s.purpose}
                {s.source_image_id ? " · image bound" : " · no image"}
              </option>
            ))}
          </select>
          {sourceSlots.length === 0 && (
            <span className={styles.fieldHint}>
              No source slots in this session. Open the Sources panel and
              create one (Main / Scene reference / Text-only reference).
            </span>
          )}
        </label>
      )}

      {slot.binding === "llm" && (
        <LLMBindingPicker
          slot={slot}
          agents={agents}
          onBind={(agentId, outputId) =>
            applyAgentBinding({
              workflowSlotLabel: slot.label,
              workflowSlotKind: slot.kind,
              newAgentId: agentId,
              newOutputId: outputId,
              agents,
              updateAgent,
              helpers,
            })
          }
        />
      )}

      <label className={styles.field}>
        <span className={styles.fieldLabel}>Description</span>
        <textarea
          className={styles.input}
          rows={2}
          value={slot.description ?? ""}
          onChange={(e) =>
            helpers.patchSlot(index, {
              description: e.currentTarget.value || null,
            })
          }
          placeholder="Hint for the LLM about what value this slot should hold"
        />
      </label>

      <div className={styles.formActions}>
        <button
          type="button"
          className={styles.danger}
          onClick={() => {
            // Drop any agent's binding to this label too — otherwise the
            // agent ends up with a dangling reference once the slot is
            // saved as deleted.
            applyAgentBinding({
              workflowSlotLabel: slot.label,
              workflowSlotKind: slot.kind,
              newAgentId: null,
              newOutputId: null,
              agents,
              updateAgent,
              helpers,
            });
            helpers.deleteSlot(index);
          }}
        >
          Unmap
        </button>
      </div>
    </>
  );
}

// --- LLM binding picker -------------------------------------------

function LLMBindingPicker({
  slot,
  agents,
  onBind,
}: {
  slot: SlotDefinition;
  agents: Agent[];
  onBind: (agentId: string | null, outputId: string | null) => void;
}) {
  const compat = useMemo(
    () => compatibleOutputsFor(slot, agents),
    [slot, agents],
  );
  const serverCurrent = compat.find((c) => c.isCurrentlyBound) ?? null;
  const serverAgentId = serverCurrent?.agentId ?? "";
  const serverOutputId = serverCurrent?.outputId ?? "";

  // Optimistic local state — the user's most recent pick, shown in
  // the dropdown immediately so it doesn't visibly bounce back to
  // "(none)" while the slot-map save and agent PATCH round-trip
  // (~300-500 ms). Cleared once the server state catches up to it.
  const [pending, setPending] = useState<{
    agentId: string;
    outputId: string;
  } | null>(null);

  const displayAgentId = pending ? pending.agentId : serverAgentId;
  const displayOutputId = pending ? pending.outputId : serverOutputId;

  useEffect(() => {
    if (!pending) return;
    if (
      serverAgentId === pending.agentId &&
      serverOutputId === pending.outputId
    ) {
      setPending(null);
    }
  }, [pending, serverAgentId, serverOutputId]);

  // Reset our local pending pick whenever the user navigates to a
  // different slot — otherwise the new slot inherits the previous
  // slot's optimistic value.
  useEffect(() => {
    setPending(null);
  }, [slot.label]);

  // Agents are listed only when they have at least one compatible
  // output — without that the dropdown becomes a list of agents the
  // user can't actually pick from.
  const agentIdsWithCompat = new Set(compat.map((c) => c.agentId));
  const availableAgents = agents.filter((a) => agentIdsWithCompat.has(a.id));

  const outputsForAgent = displayAgentId
    ? compat.filter((c) => c.agentId === displayAgentId)
    : [];

  function pick(agentId: string | null, outputId: string | null) {
    setPending(
      agentId && outputId ? { agentId, outputId } : agentId ? { agentId, outputId: "" } : null,
    );
    onBind(agentId, outputId);
  }

  return (
    <>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>Filled by agent</span>
        <select
          className={styles.input}
          value={displayAgentId}
          onChange={(e) => {
            const nextAgentId = e.currentTarget.value || null;
            if (!nextAgentId) {
              pick(null, null);
              return;
            }
            // Pick the first compatible output that isn't already bound
            // elsewhere; fall back to the first compatible at all.
            const first =
              compat.find((c) => c.agentId === nextAgentId && !c.isBoundElsewhere) ??
              compat.find((c) => c.agentId === nextAgentId) ??
              null;
            pick(nextAgentId, first?.outputId ?? null);
          }}
        >
          <option value="">(none — Generate will fail)</option>
          {availableAgents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        {availableAgents.length === 0 && (
          <span className={styles.fieldHint}>
            No agent has a compatible output. Add an{" "}
            <strong>auto</strong> or <strong>{slot.kind}</strong> output
            slot in the Agent editor first.
          </span>
        )}
      </label>

      {displayAgentId && (
        <label className={styles.field}>
          <span className={styles.fieldLabel}>Output</span>
          <select
            className={styles.input}
            value={displayOutputId}
            onChange={(e) =>
              pick(displayAgentId, e.currentTarget.value || null)
            }
          >
            <option value="">(pick an output)</option>
            {outputsForAgent.map((o) => (
              <option key={o.outputId} value={o.outputId}>
                {formatOutputOption(o)}
              </option>
            ))}
          </select>
          {outputsForAgent.some((o) => o.isBoundElsewhere) && (
            <span className={styles.fieldHint}>
              Outputs marked "taken elsewhere" are bound to a different
              workflow slot — picking one re-binds it here.
            </span>
          )}
        </label>
      )}
    </>
  );
}

function formatOutputOption(o: CompatibleOutput): string {
  const kind = o.outputKind ?? "auto";
  const tail = o.isCurrentlyBound
    ? " ✓"
    : o.isBoundElsewhere
      ? " — taken elsewhere"
      : "";
  return `${o.outputLabel} (${kind})${tail}`;
}

/** Apply a workflow-slot ↔ agent-output binding change. Walks every
 *  agent: clears any output that was bound to `workflowSlotLabel`
 *  except the new pick, and sets the new pick (auto-output kind is
 *  filled in at bind time). Each affected agent gets a single PATCH
 *  with its full output_slots array.
 *
 *  When the slot draft has unsaved edits we must persist them BEFORE
 *  PATCHing the agent — the server validates `bound_to.workflow_slot_label`
 *  against the saved slot_map, so referencing a fresh local-only slot
 *  would 422 with "unknown workflow slot label". */
async function applyAgentBinding({
  workflowSlotLabel,
  workflowSlotKind,
  newAgentId,
  newOutputId,
  agents,
  updateAgent,
  helpers,
}: {
  workflowSlotLabel: string;
  workflowSlotKind: SlotKind;
  newAgentId: string | null;
  newOutputId: string | null;
  agents: Agent[];
  updateAgent: ReturnType<typeof useUpdateAgent>;
  helpers: SlotDraftHelpers;
}) {
  if (helpers.dirty) {
    try {
      await helpers.saveAsync();
    } catch {
      // Save error is already surfaced via SlotSaveBar — bail out so
      // the agent PATCH doesn't follow with a known-bad reference.
      return;
    }
  }
  for (const a of agents) {
    let changed = false;
    let next = a.output_slots;
    // Clear any other output on this agent that was bound to the
    // same label (single-bind rule). Skip the new pick if it's on
    // this same agent.
    next = next.map((o) => {
      if (o.bound_to?.workflow_slot_label !== workflowSlotLabel) return o;
      if (a.id === newAgentId && o.id === newOutputId) return o;
      changed = true;
      return { ...o, bound_to: null };
    });
    // Set the new binding when this is the target agent.
    if (a.id === newAgentId && newOutputId) {
      next = next.map((o) => {
        if (o.id !== newOutputId) return o;
        if (
          o.bound_to?.workflow_slot_label === workflowSlotLabel &&
          (o.kind != null || o.origin !== "auto")
        ) {
          return o; // already set up
        }
        const patch: Partial<AgentOutputSlot> = {
          bound_to: { workflow_slot_label: workflowSlotLabel },
        };
        if (o.origin === "auto" && o.kind == null) {
          patch.kind = workflowSlotKind;
        }
        changed = true;
        return { ...o, ...patch };
      });
    }
    if (changed) {
      updateAgent.mutate({ agentId: a.id, body: { output_slots: next } });
    }
  }
}

function shallowEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (typeof a === "string" || typeof a === "number" || typeof a === "boolean") {
    return a === b;
  }
  // Loose JSON-string equality for objects — defaults are usually
  // primitives, so this branch is rare.
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

export type { MappingInputRow };
