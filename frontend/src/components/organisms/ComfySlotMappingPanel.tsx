import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  ALLOWED_BINDINGS,
  DEFAULT_BINDING,
  SLOT_BINDING_LABEL,
  SLOT_KINDS,
  SLOT_KIND_LABEL,
  useSaveSlotMap,
  useSlotMap,
  type CandidateInput,
  type InferredMode,
  type SlotBinding,
  type SlotDefinition,
  type SlotKind,
} from "@/api/comfy";
import styles from "./ComfySlotMappingPanel.module.css";

/** Phase 2.5 — workflow slot mapping editor.
 *
 * Replaces the Phase 2 fixed three-row table with a labelled, typed
 * slot list per workflow. The user adds slots from the candidate
 * picker, gives each one a label (and optional group), and picks a
 * binding (LLM / frozen / session image). Generation execution lands
 * in Phase 3 — this screen ends at the data model. */
export function ComfySlotMappingPanel({
  sessionId,
  onBack,
}: {
  sessionId: string;
  onBack?: () => void;
}) {
  const query = useSlotMap(sessionId);
  const save = useSaveSlotMap(sessionId);

  const [draft, setDraft] = useState<SlotDefinition[] | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  useEffect(() => {
    if (query.data && draft === null) {
      setDraft(query.data.slot_map.slots);
    }
  }, [query.data, draft]);

  const dirty = useMemo(() => {
    if (!draft || !query.data) return false;
    return JSON.stringify(draft) !== JSON.stringify(query.data.slot_map.slots);
  }, [draft, query.data]);

  if (query.isLoading || !query.data) {
    return <div className={styles.empty}>Loading slot map…</div>;
  }
  if (draft === null) return null;

  const candidates = query.data.candidates;
  const inferredMode = liveInferMode(draft, query.data.inferred_mode);
  const totalCandidates = SLOT_KINDS.reduce(
    (sum, k) => sum + candidates[k].length, 0,
  );
  const hasAnyCandidate = totalCandidates > 0;

  function updateSlot(index: number, patch: Partial<SlotDefinition>) {
    setDraft((prev) =>
      prev ? prev.map((s, i) => (i === index ? { ...s, ...patch } : s)) : prev,
    );
  }
  function deleteSlot(index: number) {
    setDraft((prev) => (prev ? prev.filter((_, i) => i !== index) : prev));
  }
  function addSlot(candidate: CandidateInput) {
    const taken = new Set(draft?.map((s) => s.label) ?? []);
    const baseLabel = defaultLabelFor(candidate);
    let label = baseLabel;
    let n = 2;
    while (taken.has(label)) label = `${baseLabel}_${n++}`;
    const slot: SlotDefinition = {
      label,
      group: null,
      ordinal: (draft?.length ?? 0) + 1,
      description: null,
      kind: candidate.kind,
      origin: { node_id: candidate.node_id, input_name: candidate.input_name },
      binding: DEFAULT_BINDING[candidate.kind],
      metadata: {},
    };
    setDraft((prev) => (prev ? [...prev, slot] : [slot]));
    setPickerOpen(false);
  }

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        {onBack && (
          <Button
            size="sm"
            icon={<Icon name="ChevronLeft" size={12} />}
            onClick={onBack}
          >
            Back to nodes
          </Button>
        )}
        <div className={styles.headBody}>
          <h2 className={styles.title}>Workflow slot mapping</h2>
          <p className={styles.subtitle}>
            Pick which inputs in the workflow sd-chisel fills at generate time.
            Each slot has a label, a kind (text, image, number, …), and a
            binding (composed by LLM / fixed value / session image). Slots can
            be left out — generation just won't touch those inputs.
          </p>
        </div>
      </div>

      <div className={styles.toolbar}>
        <Button
          size="sm"
          icon={<Icon name="Plus" size={12} />}
          onClick={() => setPickerOpen(true)}
          disabled={!hasAnyCandidate}
        >
          Add slot
        </Button>
        <Button size="sm" disabled title="Coming in Phase 2.6">
          Auto-suggest labels
        </Button>
        <span className={styles.modeBadge} data-mode={inferredMode}>
          {inferredMode}
        </span>
        <span className={styles.slotCount}>
          {draft.length} slot{draft.length === 1 ? "" : "s"}
        </span>
      </div>

      {!hasAnyCandidate && (
        <div className={styles.banner} data-tone="error" role="alert">
          <Icon name="AlertCircle" size={14} />
          <span>
            This workflow exposes no literal inputs. There's nothing to map —
            every input is either wired upstream or of a type sd-chisel
            doesn't fill.
          </span>
        </div>
      )}

      {draft.length === 0 ? (
        <div className={styles.emptyList}>
          No slots yet. Press <strong>Add slot</strong> to bind a workflow
          input to an sd-chisel slot.
        </div>
      ) : (
        <div className={styles.slots}>
          {sortedIndices(draft).map((idx) => (
            <SlotCard
              key={idx}
              slot={draft[idx]}
              candidates={candidates[draft[idx].kind]}
              draft={draft}
              onChange={(patch) => updateSlot(idx, patch)}
              onDelete={() => deleteSlot(idx)}
            />
          ))}
        </div>
      )}

      {save.isError && (
        <div className={styles.error}>{(save.error as Error).message}</div>
      )}

      <div className={styles.actionRow}>
        <Button
          variant="primary"
          disabled={!dirty || save.isPending}
          onClick={() => draft && save.mutate(draft)}
        >
          {save.isPending ? "Saving…" : "Save slot map"}
        </Button>
        {dirty && !save.isPending && (
          <Button
            onClick={() => setDraft(query.data!.slot_map.slots)}
            title="Discard unsaved changes."
          >
            Reset
          </Button>
        )}
        {!dirty && save.isSuccess && (
          <span style={{ fontSize: 12, color: "var(--text-subtle)" }}>
            Saved.
          </span>
        )}
      </div>

      {pickerOpen && (
        <CandidatePicker
          candidates={candidates}
          onPick={addSlot}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </div>
  );
}


// --- slot card ---------------------------------------------------------

function SlotCard({
  slot,
  candidates,
  draft,
  onChange,
  onDelete,
}: {
  slot: SlotDefinition;
  candidates: CandidateInput[];
  draft: SlotDefinition[];
  onChange: (patch: Partial<SlotDefinition>) => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const otherLabels = useMemo(
    () => new Set(draft.filter((s) => s !== slot).map((s) => s.label)),
    [draft, slot],
  );
  const labelInvalid =
    !slot.label.trim() ||
    !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(slot.label) ||
    otherLabels.has(slot.label);

  const originValue = `${slot.origin.node_id}::${slot.origin.input_name}`;
  const allowed = ALLOWED_BINDINGS[slot.kind];
  const selectableBindings = allowed.filter(
    (b) => b !== "library_loras", // reserved for L4
  );

  return (
    <div className={styles.slot} data-binding={slot.binding}>
      <div className={styles.slotHead}>
        <div className={styles.slotIdent}>
          <input
            className={styles.labelInput}
            value={slot.label}
            onChange={(e) => onChange({ label: e.currentTarget.value.trim() })}
            placeholder="label"
            aria-invalid={labelInvalid || undefined}
            spellCheck={false}
          />
          <input
            className={styles.groupInput}
            value={slot.group ?? ""}
            onChange={(e) =>
              onChange({ group: e.currentTarget.value.trim() || null })
            }
            placeholder="group (optional)"
            spellCheck={false}
          />
          <span className={styles.kindBadge}>{SLOT_KIND_LABEL[slot.kind]}</span>
        </div>
        <div className={styles.slotActions}>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "Collapse" : "Edit description"}
          >
            <Icon name={expanded ? "ChevronUp" : "ChevronDown"} size={12} />
          </button>
          <button
            type="button"
            className={styles.iconButton}
            onClick={onDelete}
            title="Delete slot"
            aria-label="Delete slot"
          >
            <Icon name="Trash2" size={12} />
          </button>
        </div>
      </div>

      <div className={styles.slotRow}>
        <label className={styles.fieldLabel}>Origin</label>
        <select
          className={styles.slotSelect}
          value={originValue}
          onChange={(e) => {
            const v = e.currentTarget.value;
            const [node_id, input_name] = v.split("::");
            const next = candidates.find(
              (c) => c.node_id === node_id && c.input_name === input_name,
            );
            if (!next) return;
            onChange({ origin: { node_id, input_name } });
          }}
        >
          {!candidates.find(
            (c) =>
              c.node_id === slot.origin.node_id &&
              c.input_name === slot.origin.input_name,
          ) && (
            <option value={originValue}>
              {slot.origin.node_id}.{slot.origin.input_name} — orphaned
            </option>
          )}
          {candidates.map((c) => (
            <option
              key={`${c.node_id}::${c.input_name}`}
              value={`${c.node_id}::${c.input_name}`}
            >
              {formatCandidateLabel(c)}
            </option>
          ))}
        </select>
      </div>

      <div className={styles.slotRow}>
        <label className={styles.fieldLabel}>Binding</label>
        <select
          className={styles.slotSelect}
          value={slot.binding}
          onChange={(e) => {
            const next = e.currentTarget.value as SlotBinding;
            const patch: Partial<SlotDefinition> = { binding: next };
            // Drop / seed metadata.value when toggling frozen.
            if (next === "frozen") {
              patch.metadata = {
                ...slot.metadata,
                value: defaultFrozenValue(slot, candidates),
              };
            } else if (slot.binding === "frozen") {
              const rest = { ...slot.metadata } as Record<string, unknown>;
              delete rest.value;
              patch.metadata = rest;
            }
            onChange(patch);
          }}
        >
          {selectableBindings.map((b) => (
            <option key={b} value={b}>
              {SLOT_BINDING_LABEL[b]}
            </option>
          ))}
        </select>
      </div>

      {slot.binding === "frozen" && (
        <div className={styles.slotRow}>
          <label className={styles.fieldLabel}>Frozen value</label>
          <FrozenValueEditor
            slot={slot}
            candidate={candidates.find(
              (c) =>
                c.node_id === slot.origin.node_id &&
                c.input_name === slot.origin.input_name,
            )}
            onChange={(value) =>
              onChange({ metadata: { ...slot.metadata, value } })
            }
          />
        </div>
      )}

      {expanded && (
        <div className={styles.slotRow}>
          <label className={styles.fieldLabel}>Description</label>
          <textarea
            className={styles.descTextarea}
            value={slot.description ?? ""}
            onChange={(e) =>
              onChange({ description: e.currentTarget.value || null })
            }
            placeholder="Hint for the LLM and tooltip in the workspace"
            rows={3}
          />
        </div>
      )}

      {labelInvalid && (
        <div className={styles.fieldError}>
          Label must be unique and contain only letters, digits,
          underscore, hyphen or dot.
        </div>
      )}
    </div>
  );
}


// --- frozen value editor ----------------------------------------------

function FrozenValueEditor({
  slot,
  candidate,
  onChange,
}: {
  slot: SlotDefinition;
  candidate: CandidateInput | undefined;
  onChange: (value: unknown) => void;
}) {
  const value = (slot.metadata as { value?: unknown }).value;
  const md = (candidate?.metadata ?? {}) as Record<string, unknown>;

  if (slot.kind === "boolean") {
    return (
      <select
        className={styles.slotSelect}
        value={value === true ? "true" : "false"}
        onChange={(e) => onChange(e.currentTarget.value === "true")}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (slot.kind === "number_int" || slot.kind === "number_float") {
    return (
      <input
        type="number"
        className={styles.slotInput}
        value={typeof value === "number" ? value : ""}
        step={slot.kind === "number_int" ? 1 : (md.step as number) ?? "any"}
        min={(md.min as number) ?? undefined}
        max={(md.max as number) ?? undefined}
        onChange={(e) => {
          const raw = e.currentTarget.value;
          if (raw === "") return onChange(0);
          const parsed = slot.kind === "number_int"
            ? parseInt(raw, 10)
            : parseFloat(raw);
          if (!Number.isNaN(parsed)) onChange(parsed);
        }}
      />
    );
  }
  if (
    slot.kind === "enum" ||
    slot.kind === "lora_name" ||
    slot.kind === "checkpoint_name"
  ) {
    const options = Array.isArray(md.options) ? (md.options as string[]) : [];
    return (
      <select
        className={styles.slotSelect}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.currentTarget.value)}
      >
        {!options.includes(value as string) && typeof value === "string" && (
          <option value={value}>{value} (orphaned)</option>
        )}
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }
  if (slot.kind === "multiline_text") {
    return (
      <textarea
        className={styles.descTextarea}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.currentTarget.value)}
        rows={3}
      />
    );
  }
  // text / image / image_alpha all carry a string filename or scalar.
  return (
    <input
      type="text"
      className={styles.slotInput}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.currentTarget.value)}
      placeholder={
        slot.kind === "image" || slot.kind === "image_alpha"
          ? "filename in ComfyUI input dir"
          : ""
      }
    />
  );
}


// --- candidate picker ---------------------------------------------------

function CandidatePicker({
  candidates,
  onPick,
  onClose,
}: {
  candidates: Record<SlotKind, CandidateInput[]>;
  onPick: (c: CandidateInput) => void;
  onClose: () => void;
}) {
  const nonEmpty = SLOT_KINDS.filter((k) => candidates[k].length > 0);
  const [activeKind, setActiveKind] = useState<SlotKind>(
    nonEmpty[0] ?? "text",
  );

  return (
    <div className={styles.modalBackdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <div className={styles.modalHead}>
          <h3 className={styles.modalTitle}>Add slot</h3>
          <button
            type="button"
            className={styles.iconButton}
            onClick={onClose}
            aria-label="Close"
          >
            <Icon name="X" size={14} />
          </button>
        </div>
        <p className={styles.subtitle}>
          Pick the workflow input you want to bind. The slot's kind is set
          automatically — give it a label after.
        </p>
        <div className={styles.kindTabs}>
          {nonEmpty.map((k) => (
            <button
              key={k}
              type="button"
              className={styles.kindTab}
              data-active={k === activeKind || undefined}
              onClick={() => setActiveKind(k)}
            >
              {SLOT_KIND_LABEL[k]}
              <span className={styles.kindTabCount}>
                {candidates[k].length}
              </span>
            </button>
          ))}
        </div>
        <ul className={styles.candidateList}>
          {candidates[activeKind].map((c) => (
            <li key={`${c.node_id}::${c.input_name}`}>
              <button
                type="button"
                className={styles.candidateButton}
                onClick={() => onPick(c)}
              >
                <span className={styles.candidateHead}>
                  {formatCandidateLabel(c)}
                </span>
                {previewSnippet(c.current_value) && (
                  <span className={styles.preview}>
                    "{previewSnippet(c.current_value)}"
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}


// --- helpers -----------------------------------------------------------

function liveInferMode(
  draft: SlotDefinition[],
  fallback: InferredMode,
): InferredMode {
  const hasUserImage = draft.some(
    (s) =>
      s.binding === "user_image" &&
      (s.kind === "image" || s.kind === "image_alpha"),
  );
  if (hasUserImage) return "i2i";
  if (draft.length === 0) return fallback;
  return "t2i";
}

function sortedIndices(slots: SlotDefinition[]): number[] {
  return slots
    .map((_, i) => i)
    .sort((a, b) => {
      const sa = slots[a];
      const sb = slots[b];
      const ga = sa.group ?? "";
      const gb = sb.group ?? "";
      if (ga !== gb) return ga.localeCompare(gb);
      const oa = sa.ordinal ?? Number.MAX_SAFE_INTEGER;
      const ob = sb.ordinal ?? Number.MAX_SAFE_INTEGER;
      if (oa !== ob) return oa - ob;
      return sa.label.localeCompare(sb.label);
    });
}

function defaultLabelFor(c: CandidateInput): string {
  const base = `${c.node_class_type}_${c.input_name}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return base || "slot";
}

function defaultFrozenValue(
  slot: SlotDefinition,
  candidates: CandidateInput[],
): unknown {
  const cand = candidates.find(
    (c) =>
      c.node_id === slot.origin.node_id &&
      c.input_name === slot.origin.input_name,
  );
  if (cand && cand.current_value !== undefined && cand.current_value !== null) {
    return cand.current_value;
  }
  const md = (cand?.metadata ?? {}) as Record<string, unknown>;
  if ("default" in md) return md.default;
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

function formatCandidateLabel(c: CandidateInput): string {
  const heading =
    c.node_title ?? c.node_display_name ?? c.node_class_type;
  const flag = c.node_in_catalog ? "" : " · uncatalogued";
  return `${heading}.${c.input_name} (#${c.node_id})${flag}`;
}

function previewSnippet(value: unknown): string {
  if (value == null) return "";
  const s = typeof value === "string" ? value : JSON.stringify(value);
  const oneLine = s.replace(/\s+/g, " ").trim();
  return oneLine.length > 60 ? oneLine.slice(0, 60) + "…" : oneLine;
}
