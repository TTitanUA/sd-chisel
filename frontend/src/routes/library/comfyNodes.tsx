import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { MarkdownView } from "@/components/molecules/MarkdownField";
import {
  useNode,
  useNodes,
  usePack,
  usePacks,
  useUpdateNode,
  type NodeInputSemantic,
  type NodeListItem,
  type Pack,
  type PackDetail,
} from "@/api/comfy";
import styles from "./comfyNodes.module.css";

const BASE = "/library/comfy-nodes";

type Selection =
  | { kind: "pack"; name: string }
  | { kind: "node"; classType: string }
  | null;

export default function ComfyNodesRoute() {
  const params = useParams<{ "*"?: string }>();
  const navigate = useNavigate();
  const splat = (params["*"] ?? "").split("/").filter(Boolean);

  const selection: Selection = useMemo(() => {
    if (splat[0] === "packs" && splat[1]) {
      return { kind: "pack", name: decodeURIComponent(splat[1]) };
    }
    if (splat[0] === "nodes" && splat[1]) {
      return { kind: "node", classType: decodeURIComponent(splat[1]) };
    }
    return null;
  }, [splat]);

  const [search, setSearch] = useState("");
  const [packFilter, setPackFilter] = useState<string | null>(null);

  const packs = usePacks();
  const nodes = useNodes({
    q: search || undefined,
    pack: packFilter ?? undefined,
  });

  const filteredPacks = useMemo(() => {
    const all = packs.data ?? [];
    if (packFilter) return all.filter((p) => p.name === packFilter);
    if (!search) return all;
    const needle = search.toLowerCase();
    return all.filter(
      (p) =>
        p.name.toLowerCase().includes(needle) ||
        p.display_name.toLowerCase().includes(needle) ||
        (p.description ?? "").toLowerCase().includes(needle),
    );
  }, [packs.data, packFilter, search]);

  return (
    <div className={styles.page}>
      <aside className={styles.list}>
        <div className={styles.listHead}>
          <TextInput
            label="Search"
            placeholder="Filter packs and nodes…"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            className={styles.search}
          />
          {(packs.data?.length ?? 0) > 0 && (
            <div className={styles.filterRow}>
              <button
                type="button"
                className={[
                  styles.chip,
                  packFilter === null ? styles.chipActive : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => setPackFilter(null)}
              >
                All packs
              </button>
              {(packs.data ?? []).map((p) => (
                <button
                  key={p.name}
                  type="button"
                  className={[
                    styles.chip,
                    packFilter === p.name ? styles.chipActive : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() =>
                    setPackFilter(packFilter === p.name ? null : p.name)
                  }
                >
                  {p.display_name}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className={styles.scroll}>
          {(packs.data?.length ?? 0) === 0 && (nodes.data?.length ?? 0) === 0 && (
            <div className={styles.empty}>
              No nodes imported yet. Import nodes from the readiness panel of
              a comfy session — the per-node import wizard will populate this
              section.
            </div>
          )}

          {filteredPacks.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionTitle}>Packs</div>
              {filteredPacks.map((p) => (
                <PackRow
                  key={p.name}
                  pack={p}
                  active={selection?.kind === "pack" && selection.name === p.name}
                  onClick={() =>
                    navigate(`${BASE}/packs/${encodeURIComponent(p.name)}`)
                  }
                />
              ))}
            </div>
          )}

          {(nodes.data ?? []).length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionTitle}>Nodes</div>
              {(nodes.data ?? []).map((n) => (
                <NodeRow
                  key={n.class_type}
                  node={n}
                  active={
                    selection?.kind === "node" && selection.classType === n.class_type
                  }
                  onClick={() =>
                    navigate(
                      `${BASE}/nodes/${encodeURIComponent(n.class_type)}`,
                    )
                  }
                />
              ))}
            </div>
          )}
        </div>
      </aside>
      <main>
        {selection === null && <DefaultDetail />}
        {selection?.kind === "pack" && <PackDetailPane name={selection.name} />}
        {selection?.kind === "node" && (
          <NodeDetailPane classType={selection.classType} />
        )}
      </main>
    </div>
  );
}


function PackRow({
  pack, active, onClick,
}: {
  pack: Pack;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[styles.row, active ? styles.rowActive : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <span className={styles.rowKindBadge}>Pack</span>
      <span className={styles.rowMain}>
        <span className={styles.rowName}>{pack.display_name}</span>
        <span className={styles.rowMeta}>
          {pack.node_count} node{pack.node_count === 1 ? "" : "s"}
          {pack.publisher_id && ` · ${pack.publisher_id}`}
        </span>
      </span>
    </button>
  );
}


function NodeRow({
  node, active, onClick,
}: {
  node: NodeListItem;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[styles.row, active ? styles.rowActive : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <span className={styles.rowKindBadge} data-kind="node">Node</span>
      <span className={styles.rowMain}>
        <span className={styles.rowName}>{node.display_name}</span>
        <span className={styles.rowMeta}>
          {node.pack_name}
          {node.has_override && " · edited"}
        </span>
      </span>
    </button>
  );
}


function DefaultDetail() {
  return (
    <div className={styles.detailEmpty}>
      Pick a pack or a node from the list to see its details.
    </div>
  );
}


function PackDetailPane({ name }: { name: string }) {
  const pack = usePack(name);
  const navigate = useNavigate();

  if (pack.isLoading) {
    return <div className={styles.detailEmpty}>Loading…</div>;
  }
  if (pack.isError || !pack.data) {
    return (
      <div className={styles.detailEmpty}>
        Pack "{name}" not found.
      </div>
    );
  }

  const p: PackDetail = pack.data;

  return (
    <div className={styles.detail}>
      <div className={styles.detailHead}>
        <h2 className={styles.detailTitle}>{p.display_name}</h2>
        <div className={styles.detailMeta}>
          <span>{p.name}</span>
          {p.version && <span>v{p.version}</span>}
          {p.publisher_id && <span>by {p.publisher_id}</span>}
          {p.dir_path && <span>{p.dir_path}</span>}
          {p.repo_url && (
            <a href={p.repo_url} target="_blank" rel="noreferrer">
              repo ↗
            </a>
          )}
        </div>
        {p.description && <div className={styles.detailDescription}>{p.description}</div>}
      </div>

      <div className={styles.detailSection}>
        <div className={styles.detailSectionTitle}>
          Nodes ({p.nodes.length})
        </div>
        {p.nodes.length === 0 ? (
          <div className={styles.empty}>
            No nodes from this pack imported yet.
          </div>
        ) : (
          <div className={styles.subNodes}>
            {p.nodes.map((n) => (
              <button
                key={n.class_type}
                type="button"
                className={styles.subNodeRow}
                onClick={() =>
                  navigate(`${BASE}/nodes/${encodeURIComponent(n.class_type)}`)
                }
              >
                <span style={{ fontWeight: 500 }}>{n.display_name}</span>
                <span style={{ flex: 1 }} />
                <span style={{ color: "var(--text-subtle)", fontSize: 11 }}>
                  {n.class_type}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {p.readme_md && (
        <div className={styles.detailSection}>
          <div className={styles.detailSectionTitle}>README</div>
          <div className={styles.markdownBlock}>
            <MarkdownView value={p.readme_md} />
          </div>
        </div>
      )}
    </div>
  );
}


function NodeDetailPane({ classType }: { classType: string }) {
  const node = useNode(classType);
  const update = useUpdateNode(classType);

  const [draftDescription, setDraftDescription] = useState("");
  const [draftSemantic, setDraftSemantic] = useState<NodeInputSemantic[]>([]);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    if (node.data) {
      setDraftDescription(node.data.description_md);
      setDraftSemantic(node.data.inputs_semantic);
    }
  }, [node.data]);

  if (node.isLoading) {
    return <div className={styles.detailEmpty}>Loading…</div>;
  }
  if (node.isError || !node.data) {
    return (
      <div className={styles.detailEmpty}>
        Node "{classType}" not found.
      </div>
    );
  }

  const n = node.data;
  const dirty =
    draftDescription !== n.description_md ||
    JSON.stringify(draftSemantic) !== JSON.stringify(n.inputs_semantic);

  return (
    <div className={styles.detail}>
      <div className={styles.detailHead}>
        <h2 className={styles.detailTitle}>
          {n.display_name}{" "}
          {n.has_override && (
            <span className={styles.overrideBadge}>edited</span>
          )}
        </h2>
        <div className={styles.detailMeta}>
          <span>class_type: {n.class_type}</span>
          <span>pack: {n.pack_name}</span>
          {n.category && <span>category: {n.category}</span>}
          {!n.requires_semantic_config && (
            <span>auto-ready (no semantic config required)</span>
          )}
        </div>
      </div>

      <div className={styles.detailSection}>
        <div className={styles.detailSectionTitle}>Description</div>
        <textarea
          value={draftDescription}
          onChange={(e) => setDraftDescription(e.currentTarget.value)}
          rows={5}
          style={{
            width: "100%",
            padding: "8px 10px",
            border: "1px solid var(--border)",
            borderRadius: 4,
            background: "var(--bg)",
            color: "inherit",
            font: "inherit",
            fontSize: 13,
            lineHeight: 1.5,
            resize: "vertical",
          }}
          placeholder="Markdown description…"
        />
      </div>

      <div className={styles.detailSection}>
        <div className={styles.detailSectionTitle}>
          Inputs — optional notes shown in the slot-map editor
        </div>
        {draftSemantic.length === 0 ? (
          <div className={styles.empty}>
            No inputs recorded. (Inputs come from the per-node import
            wizard, which writes them to the catalog alongside the raw schema.)
          </div>
        ) : (
          <div className={styles.semanticEditor}>
            <span className={styles.semanticEditorHead}>name</span>
            <span className={styles.semanticEditorHead}>notes</span>
            {draftSemantic.map((row, idx) => (
              <SemanticRow
                key={`${row.name}-${idx}`}
                row={row}
                onChange={(next) => {
                  const copy = draftSemantic.slice();
                  copy[idx] = next;
                  setDraftSemantic(copy);
                }}
              />
            ))}
          </div>
        )}
      </div>

      <div className={styles.editorButtons}>
        <Button
          variant="primary"
          disabled={!dirty || update.isPending}
          onClick={() =>
            update.mutate({
              description_md: draftDescription,
              inputs_semantic: draftSemantic,
            })
          }
        >
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
        {n.has_override && (
          <Button
            disabled={update.isPending}
            onClick={() =>
              update.mutate({ description_md: null, inputs_semantic: null, category: null })
            }
            title="Drop the user-edit overlay; revert to the originally imported values."
          >
            Reset to imported
          </Button>
        )}
        {update.isError && (
          <span className={styles.error}>
            {(update.error as Error).message}
          </span>
        )}
      </div>

      <div className={styles.detailSection}>
        <div
          className={styles.actionRow}
          style={{ justifyContent: "space-between" }}
        >
          <span className={styles.detailSectionTitle}>Raw INPUT_TYPES</span>
          <Button
            size="sm"
            icon={
              <Icon name={showRaw ? "ChevronDown" : "ChevronRight"} size={12} />
            }
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? "Hide" : "Show"}
          </Button>
        </div>
        {showRaw && (
          <pre className={styles.rawSchema}>
            {JSON.stringify(
              { inputs: n.inputs_raw, outputs: n.outputs_raw },
              null,
              2,
            )}
          </pre>
        )}
      </div>
    </div>
  );
}


function SemanticRow({
  row, onChange,
}: {
  row: NodeInputSemantic;
  onChange: (next: NodeInputSemantic) => void;
}) {
  return (
    <>
      <span className={styles.inputsName}>{row.name}</span>
      <input
        type="text"
        value={row.notes ?? ""}
        onChange={(e) =>
          onChange({
            ...row,
            notes: e.currentTarget.value || null,
          })
        }
        placeholder="optional notes"
      />
    </>
  );
}
