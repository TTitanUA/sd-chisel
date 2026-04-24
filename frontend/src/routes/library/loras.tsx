import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Badge } from "@/components/atoms/Badge";
import {
  libraryApi,
  useFamilies,
  useLibraryInvalidation,
  useLoras,
  type Lora,
  type LoraCreate,
  type LoraUpdate,
} from "@/api/library";
import { LibraryCrud, type CrudMode } from "@/components/organisms/LibraryCrud";
import { LibraryDetailBlock, LibraryDetailMeta } from "@/components/molecules/LibraryV2Detail";
import detailStyles from "@/components/molecules/LibraryV2Detail.module.css";
import { LoraForm } from "@/components/organisms/LoraForm";
import { formatUpdated } from "@/lib/formatUpdated";
import { ModelFilterControls } from "./ModelFilterControls";
import listStyles from "@/components/organisms/LibraryCrud.module.css";

export default function LorasRoute() {
  const [search, setSearch] = useState("");
  const [familyIdFilter, setFamilyIdFilter] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const loras = useLoras({ q: search });

  const filteredLoras = useMemo(() => {
    let list = loras.data ?? [];
    if (familyIdFilter) {
      list = list.filter((l) => l.family_id === familyIdFilter);
    }
    return list;
  }, [loras.data, familyIdFilter]);

  const selected = useMemo(() => {
    const rows = loras.data ?? [];
    return rows.find((l) => l.name === selectedName) ?? rows[0] ?? null;
  }, [loras.data, selectedName]);

  const create = useMutation({ mutationFn: libraryApi.createLora, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ name, body }: { name: string; body: LoraUpdate }) => libraryApi.updateLora(name, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteLora, onSuccess: invalidate });

  function submit(body: LoraCreate | LoraUpdate) {
    if (mode === "create") {
      create.mutate(body as LoraCreate, {
        onSuccess: (lora: Lora) => {
          setSelectedName(lora.name);
          setMode("detail");
        },
      });
      return;
    }
    if (selected) {
      update.mutate({ name: selected.name, body: body as LoraUpdate }, { onSuccess: () => setMode("detail") });
    }
  }

  const rows = filteredLoras.map((lora) => ({
    id: lora.name,
    primary: lora.name,
    rightMeta: lora.family_id.toUpperCase(),
    tags: lora.tags.slice(0, 2),
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? loras.error ?? families.error;
  const total = loras.data?.length ?? 0;

  const detailTitle =
    mode === "create" ? "New LoRA" : mode === "edit" && selected ? `Edit · ${selected.name}` : selected?.name ?? "—";
  const detailTitleVariant: "mono" | "default" =
    mode === "detail" && selected ? "mono" : mode === "edit" && selected ? "mono" : "default";

  return (
    <LibraryCrud
      listTitle="LoRA"
      filteredCount={filteredLoras.length}
      totalCount={total}
      searchPlaceholder="Search name, tag, trigger…"
      search={search}
      onSearch={setSearch}
      items={rows}
      selectedId={selected?.name ?? null}
      onSelect={(id) => {
        setSelectedName(id);
        setMode("detail");
      }}
      onNew={() => setMode("create")}
      mode={mode}
      detailEyebrow="LoRA"
      detailTitle={detailTitle}
      detailTitleVariant={detailTitleVariant}
      onEdit={selected && mode === "detail" ? () => setMode("edit") : undefined}
      onDelete={
        selected && mode === "detail"
          ? () => remove.mutate(selected.name, { onSuccess: () => setSelectedName(null) })
          : undefined
      }
      filters={
        <ModelFilterControls
          families={familyRows}
          familyId={familyIdFilter}
          onChange={setFamilyIdFilter}
        />
      }
      emptySelection={mode === "detail" && !selected}
      emptySelectionMessage="Select a LoRA to see details"
    >
      {error && (
        <div role="alert" className={listStyles.error}>
          {String(error)}
        </div>
      )}
      {mode === "create" && (
        <LoraForm
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={create.isPending}
        />
      )}
      {mode === "edit" && selected && (
        <LoraForm
          lora={selected}
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      )}
      {mode === "detail" && selected && (
        <>
          <LibraryDetailMeta
            cells={[
              {
                label: "Family",
                value: <Badge variant="neutral">{selected.family_id.toUpperCase()}</Badge>,
              },
              {
                label: "Weight · rec.",
                value: (
                  <code className="ds-code">
                    {selected.recommended_weight == null
                      ? "—"
                      : selected.recommended_weight.toFixed(2)}
                  </code>
                ),
              },
              {
                label: "Author",
                value: <span>{selected.author ?? "—"}</span>,
              },
              {
                label: "Updated",
                value: <span>{formatUpdated(selected.updated_at)}</span>,
              },
            ]}
          />
          <LibraryDetailBlock label="Trigger words">
            <div className={detailStyles.codeRow}>
              {selected.trigger_words.length === 0 ? (
                <span className="ds-label-caps" style={{ fontSize: 12, color: "var(--text-subtle)" }}>
                  —
                </span>
              ) : (
                selected.trigger_words.map((t) => (
                  <code key={t} className="ds-code">
                    {t}
                  </code>
                ))
              )}
            </div>
          </LibraryDetailBlock>
          <LibraryDetailBlock label="Tags">
            <div className={detailStyles.codeRow} style={{ gap: 6 }}>
              {selected.tags.length === 0 ? (
                <span style={{ color: "var(--text-subtle)", fontSize: 13 }}>—</span>
              ) : (
                selected.tags.map((tag) => (
                  <Badge key={tag} variant="accent">
                    {tag}
                  </Badge>
                ))
              )}
            </div>
          </LibraryDetailBlock>
          <LibraryDetailBlock label="Description" isLast>
            <p className={detailStyles.desc}>{selected.description || "—"}</p>
          </LibraryDetailBlock>
        </>
      )}
    </LibraryCrud>
  );
}
