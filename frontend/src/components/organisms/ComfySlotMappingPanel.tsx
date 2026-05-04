import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  SLOT_KIND,
  SLOT_LABEL,
  SLOT_NAMES,
  useSaveSlotMap,
  useSlotMap,
  type CandidateInput,
  type SlotMap,
  type SlotName,
} from "@/api/comfy";
import styles from "./ComfySlotMappingPanel.module.css";

/** Phase 2 — workflow slot mapping screen.
 *
 * Lives on the page after readiness once every node class is green.
 * The user assigns each sd-chisel logical slot (positive prompt,
 * negative prompt, main image) to a literal-valued input in the
 * workflow graph. All slots are optional; saving partial maps is
 * fine — Phase 3 generation just skips slots left null. */
export function ComfySlotMappingPanel({
  sessionId,
  onBack,
}: {
  sessionId: string;
  onBack?: () => void;
}) {
  const query = useSlotMap(sessionId);
  const save = useSaveSlotMap(sessionId);

  const [draft, setDraft] = useState<SlotMap | null>(null);

  useEffect(() => {
    if (query.data && draft === null) {
      setDraft(query.data.slot_map);
    }
  }, [query.data, draft]);

  const dirty = useMemo(() => {
    if (!draft || !query.data) return false;
    return JSON.stringify(draft) !== JSON.stringify(query.data.slot_map);
  }, [draft, query.data]);

  if (query.isLoading || !query.data) {
    return <div className={styles.empty}>Loading slot map…</div>;
  }

  if (draft === null) {
    return null;
  }

  const candidates = query.data.candidates;

  function setSlot(slot: SlotName, assignment: SlotMap[SlotName]) {
    setDraft((prev) => (prev ? { ...prev, [slot]: assignment } : prev));
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
            Pick which input in the workflow each sd-chisel slot fills at
            generate time. Only literal-valued inputs (text strings and
            image-upload pickers) are eligible — sampler / size / model
            choices stay as they are in the saved workflow. Slots can be
            left blank; that just means sd-chisel won't touch that input.
          </p>
        </div>
      </div>

      {candidates.text.length === 0 && candidates.image.length === 0 && (
        <div className={styles.banner} data-tone="error" role="alert">
          <Icon name="AlertCircle" size={14} />
          <span>
            This workflow exposes no literal text or image inputs. There's
            nothing to map — every input is either wired upstream or of a
            type sd-chisel doesn't fill (numbers, samplers, model names).
          </span>
        </div>
      )}

      <div className={styles.slots}>
        {SLOT_NAMES.map((slot) => {
          const kind = SLOT_KIND[slot];
          const bucket = kind === "text" ? candidates.text : candidates.image;
          return (
            <SlotRow
              key={slot}
              slot={slot}
              kind={kind}
              candidates={bucket}
              assignment={draft[slot]}
              onChange={(next) => setSlot(slot, next)}
            />
          );
        })}
      </div>

      {save.isError && (
        <div className={styles.error}>
          {(save.error as Error).message}
        </div>
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
            onClick={() => setDraft(query.data!.slot_map)}
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
    </div>
  );
}


function SlotRow({
  slot,
  kind,
  candidates,
  assignment,
  onChange,
}: {
  slot: SlotName;
  kind: "text" | "image";
  candidates: CandidateInput[];
  assignment: { node_id: string; input_name: string } | null;
  onChange: (next: { node_id: string; input_name: string } | null) => void;
}) {
  const value = assignment
    ? `${assignment.node_id}::${assignment.input_name}`
    : "";

  const selected = assignment
    ? candidates.find(
        (c) =>
          c.node_id === assignment.node_id &&
          c.input_name === assignment.input_name,
      ) ?? null
    : null;

  return (
    <div className={styles.slot}>
      <div className={styles.slotLabel}>
        <span className={styles.slotName}>{SLOT_LABEL[slot]}</span>
        <span className={styles.slotKind}>{kind}</span>
      </div>
      <select
        className={styles.slotSelect}
        value={value}
        onChange={(e) => {
          const v = e.currentTarget.value;
          if (!v) {
            onChange(null);
            return;
          }
          const [node_id, input_name] = v.split("::");
          onChange({ node_id, input_name });
        }}
        disabled={candidates.length === 0}
      >
        <option value="">— unassigned —</option>
        {candidates.map((c) => (
          <option
            key={`${c.node_id}::${c.input_name}`}
            value={`${c.node_id}::${c.input_name}`}
          >
            {formatCandidateLabel(c)}
          </option>
        ))}
      </select>
      {selected && (
        <span className={styles.preview} title={String(selected.current_value ?? "")}>
          {previewSnippet(selected.current_value)}
        </span>
      )}
      {selected && selected.multiline && typeof selected.current_value === "string" && (
        <pre className={styles.previewBlock}>{selected.current_value}</pre>
      )}
    </div>
  );
}


function formatCandidateLabel(c: CandidateInput): string {
  // Lead with the user-set node title from the ComfyUI canvas when
  // present — that's what tells two nodes of the same class apart
  // ("Positive prompt" vs "Negative prompt"). Fall back to the
  // catalog display_name, then the class_type. Append a short
  // preview of the current literal so it's always obvious which
  // option corresponds to which row in the graph.
  const heading =
    c.node_title ??
    c.node_display_name ??
    c.node_class_type;
  const preview = previewSnippet(c.current_value);
  const previewSuffix = preview ? ` — "${preview}"` : "";
  const flag = c.node_in_catalog ? "" : " · uncatalogued";
  return `${heading}.${c.input_name} (#${c.node_id})${previewSuffix}${flag}`;
}


function previewSnippet(value: unknown): string {
  if (value == null) return "";
  const s = typeof value === "string" ? value : JSON.stringify(value);
  const oneLine = s.replace(/\s+/g, " ").trim();
  return oneLine.length > 40 ? oneLine.slice(0, 40) + "…" : oneLine;
}
