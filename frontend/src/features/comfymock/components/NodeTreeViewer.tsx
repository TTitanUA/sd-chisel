/** Read-only tree of the workflow graph. One row per node + indented
 *  rows for each input. Click an input → callback opens a drawer
 *  showing how that input is bound (frozen / agent / user image /
 *  unbound). See docs/comfy-agents-ui-mock-plan.md. */
import { useMemo } from "react";
import type { SlotMapV2, Workflow } from "@/api/comfy";
import styles from "./NodeTreeViewer.module.css";

type NodeRow = {
  nodeId: string;
  classType: string;
  title: string | null;
  inputs: Array<{
    name: string;
    rawValue: unknown;
    boundLabel: string | null;
  }>;
};

export function NodeTreeViewer({
  workflow,
  slotMap,
  onInputClick,
}: {
  workflow: Workflow | null | undefined;
  slotMap: SlotMapV2 | null | undefined;
  onInputClick?: (nodeId: string, inputName: string) => void;
}) {
  const rows = useMemo(() => {
    if (!workflow) return [];
    return buildRows(workflow, slotMap);
  }, [workflow, slotMap]);

  if (!workflow) {
    return <div className={styles.empty}>Workflow not loaded.</div>;
  }
  if (rows.length === 0) {
    return <div className={styles.empty}>This workflow has no nodes?</div>;
  }
  return (
    <div className={styles.tree}>
      {rows.map((row) => (
        <div key={row.nodeId} className={styles.node}>
          <div className={styles.nodeHead}>
            <span className={styles.nodeId}>#{row.nodeId}</span>
            <span className={styles.classType}>{row.classType}</span>
            {row.title && <span className={styles.title}>{row.title}</span>}
          </div>
          <div className={styles.inputs}>
            {row.inputs.map((input) => (
              <button
                key={input.name}
                type="button"
                className={`${styles.input} ${
                  input.boundLabel ? styles.bound : ""
                }`}
                onClick={() => onInputClick?.(row.nodeId, input.name)}
                disabled={!onInputClick}
                title="Click for binding details."
              >
                <span className={styles.inputName}>{input.name}</span>
                <span className={styles.inputValue}>
                  {input.boundLabel ? (
                    <em>↳ {input.boundLabel}</em>
                  ) : (
                    formatValue(input.rawValue)
                  )}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function buildRows(workflow: Workflow, slotMap: SlotMapV2 | null | undefined): NodeRow[] {
  const slotByOrigin = new Map<string, string>();
  if (slotMap) {
    for (const s of slotMap.slots) {
      slotByOrigin.set(`${s.origin.node_id}:${s.origin.input_name}`, s.label);
    }
  }
  const ids = Object.keys(workflow.graph).sort((a, b) => {
    const na = parseInt(a, 10);
    const nb = parseInt(b, 10);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    return a.localeCompare(b);
  });
  const out: NodeRow[] = [];
  for (const id of ids) {
    const node = workflow.graph[id] as
      | { class_type?: string; inputs?: Record<string, unknown>; _meta?: { title?: string } }
      | undefined;
    if (!node || typeof node !== "object") continue;
    // Wired inputs (those connected from another node's output) aren't
    // directly fillable from sd-chisel — agents bind to literals only.
    // Hide them, and if a node ends up with zero non-wired inputs hide
    // the node entirely so the tree only surfaces actionable rows.
    const inputs = Object.entries(node.inputs ?? {})
      .filter(([, value]) => !isWired(value))
      .map(([name, value]) => ({
        name,
        rawValue: value,
        boundLabel: slotByOrigin.get(`${id}:${name}`) ?? null,
      }));
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

function isWired(v: unknown): boolean {
  return (
    Array.isArray(v) &&
    v.length === 2 &&
    typeof v[0] === "string" &&
    typeof v[1] === "number"
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v.length > 64 ? v.slice(0, 64) + "…" : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return "(?)";
  }
}
