/** Output slot map editor (PR-2 prep, symmetric to slot map).
 *
 *  Lists every SaveImage node in the workflow as a row with an
 *  editable label. The user picks which outputs Phase 3 will copy
 *  into ``data/images/<sid>/output/<gid>/<label>.<ext>`` and what to
 *  call them. Default labels come from the SaveImage's
 *  ``filename_prefix`` literal (sanitised by the backend); the user
 *  can rename freely. Save commits the full list via PUT.
 *
 *  Removing an entry with the trash icon excludes that SaveImage
 *  from collection — Phase 3 will report it as an "untracked"
 *  warning at run time, not copy the file. The chip below the row
 *  shows ``filename_prefix`` from the graph so the user can match
 *  rows to their SaveImage nodes at a glance.
 *
 *  Custom savers (SaveImageS3, video encoders, …) are filtered out
 *  by the backend's ``IMAGE_SAVER_CLASSES`` allow-list — they don't
 *  show up here at all. */
import { useEffect, useMemo, useState } from "react";
import {
  useOutputSlotMap,
  useSaveOutputSlotMap,
  type OutputCandidate,
  type OutputSlotDefinition,
} from "@/api/comfy";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { useComfy } from "../state/useComfy";
import styles from "./InspectorPanels.module.css";

type Row = {
  node_id: string;
  candidate: OutputCandidate;
  // present = include this node in the output map; absent = exclude.
  label: string | null;
};

function buildInitialRows(
  candidates: OutputCandidate[],
  saved: OutputSlotDefinition[],
): Row[] {
  const byId = new Map(saved.map((o) => [o.node_id, o.label]));
  return candidates.map((c) => ({
    node_id: c.node_id,
    candidate: c,
    label: byId.has(c.node_id) ? byId.get(c.node_id)! : null,
  }));
}

export function OutputsPanel() {
  const { session } = useComfy();
  const { data, isLoading } = useOutputSlotMap(session.id);
  const save = useSaveOutputSlotMap(session.id);

  const [rows, setRows] = useState<Row[]>([]);
  const [autoSeeded, setAutoSeeded] = useState(false);

  useEffect(() => {
    if (!data) return;
    setRows(buildInitialRows(data.candidates, data.output_slot_map.outputs));
    setAutoSeeded(true);
  }, [data]);

  // Track dirty by comparing the editable rows to what the server
  // last gave us — same as the slot-map drawer.
  const dirty = useMemo(() => {
    if (!data) return false;
    const incoming: OutputSlotDefinition[] = rows
      .filter((r) => r.label !== null)
      .map((r) => ({
        node_id: r.node_id,
        label: r.label!,
        kind: "image" as const,
      }));
    const saved = data.output_slot_map.outputs;
    if (incoming.length !== saved.length) return true;
    for (let i = 0; i < incoming.length; i++) {
      if (
        incoming[i].node_id !== saved[i].node_id ||
        incoming[i].label !== saved[i].label
      )
        return true;
    }
    return false;
  }, [rows, data]);

  const labelDuplicates = useMemo(() => {
    const seen = new Map<string, number>();
    for (const r of rows) {
      if (r.label === null) continue;
      seen.set(r.label, (seen.get(r.label) ?? 0) + 1);
    }
    const dupes = new Set<string>();
    for (const [label, n] of seen) if (n > 1) dupes.add(label);
    return dupes;
  }, [rows]);

  const labelInvalid = useMemo(() => {
    const re = /^[A-Za-z0-9][A-Za-z0-9_.\-]*$/;
    return new Set(
      rows
        .filter((r) => r.label !== null && !re.test(r.label!))
        .map((r) => r.node_id),
    );
  }, [rows]);

  const canSave =
    dirty
    && !save.isPending
    && labelDuplicates.size === 0
    && labelInvalid.size === 0
    && rows.some((r) => r.label !== null);

  function patchRow(nodeId: string, patch: Partial<Row>) {
    setRows((prev) =>
      prev.map((r) => (r.node_id === nodeId ? { ...r, ...patch } : r)),
    );
  }

  function commit() {
    const outputs: OutputSlotDefinition[] = rows
      .filter((r) => r.label !== null)
      .map((r) => ({
        node_id: r.node_id,
        label: r.label!,
        kind: "image" as const,
      }));
    save.mutate(outputs);
  }

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>
          Outputs ({rows.filter((r) => r.label !== null).length}/{rows.length})
        </span>
      </div>
      <div className={styles.body}>
        <div className={styles.list}>
          {isLoading && !autoSeeded && (
            <div className={styles.empty}>Loading…</div>
          )}
          {autoSeeded && rows.length === 0 && (
            <div className={styles.empty}>
              No <code>SaveImage</code> nodes in this workflow. Add one to the
              workflow in ComfyUI to capture results.
            </div>
          )}
          {rows.map((r) => {
            const included = r.label !== null;
            const dup = included && labelDuplicates.has(r.label!);
            const invalid = included && labelInvalid.has(r.node_id);
            return (
              <div key={r.node_id} className={styles.row}>
                <div className={styles.rowHead}>
                  <strong>#{r.node_id}</strong>
                  <span className={styles.chip}>
                    {r.candidate.node_class_type}
                  </span>
                  {!included && (
                    <span className={styles.chip}>excluded</span>
                  )}
                </div>
                {r.candidate.filename_prefix && (
                  <div className={styles.dim}>
                    prefix: <code>{r.candidate.filename_prefix}</code>
                  </div>
                )}
                {included ? (
                  <>
                    <input
                      aria-label={`Label for SaveImage #${r.node_id}`}
                      style={{
                        width: "100%",
                        fontSize: 12,
                        border: `1px solid ${
                          dup || invalid
                            ? "var(--danger)"
                            : "var(--border)"
                        }`,
                        borderRadius: 4,
                        padding: "4px 6px",
                        background: "var(--surface)",
                      }}
                      value={r.label ?? ""}
                      onChange={(e) =>
                        patchRow(r.node_id, { label: e.currentTarget.value })
                      }
                    />
                    {(dup || invalid) && (
                      <div className={styles.dim} style={{ color: "var(--danger)" }}>
                        {dup
                          ? "duplicate label"
                          : "use only A–Z, a–z, 0–9, '_', '.', '-' (start alphanumeric)"}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => patchRow(r.node_id, { label: null })}
                      style={{
                        background: "transparent",
                        border: "1px solid var(--border)",
                        borderRadius: 4,
                        fontSize: 11,
                        padding: "2px 6px",
                        alignSelf: "flex-start",
                      }}
                    >
                      <Icon name="Trash2" size={11} /> exclude from outputs
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      const fallback =
                        r.candidate.filename_prefix?.replace(
                          /[^A-Za-z0-9_.\-]+/g,
                          "_",
                        ) ?? `output_${r.node_id}`;
                      patchRow(r.node_id, { label: fallback });
                    }}
                    style={{
                      background: "transparent",
                      border: "1px solid var(--border)",
                      borderRadius: 4,
                      fontSize: 11,
                      padding: "2px 6px",
                      alignSelf: "flex-start",
                    }}
                  >
                    + include
                  </button>
                )}
              </div>
            );
          })}
        </div>
        {rows.length > 0 && (
          <div
            style={{
              borderTop: "1px solid var(--border)",
              padding: "8px 12px",
              display: "flex",
              gap: 8,
              alignItems: "center",
              fontSize: 11,
              color: "var(--text-muted)",
            }}
          >
            {save.isError && (
              <span style={{ color: "var(--danger)" }}>
                Save failed: {String(save.error)}
              </span>
            )}
            {save.isSuccess && !dirty && <span>Saved.</span>}
            <div style={{ flex: 1 }} />
            <Button
              type="button"
              variant="primary"
              onClick={commit}
              disabled={!canSave}
            >
              {save.isPending ? "Saving…" : "Save outputs"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
