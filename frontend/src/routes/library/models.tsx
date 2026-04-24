import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Badge } from "@/components/atoms/Badge";
import {
  libraryApi,
  useFamilies,
  useLibraryInvalidation,
  useModels,
  type Model,
  type ModelCreate,
  type ModelUpdate,
} from "@/api/library";
import { LibraryCrud, type CrudMode } from "@/components/organisms/LibraryCrud";
import { LibraryDetailBlock, LibraryDetailMeta } from "@/components/molecules/LibraryV2Detail";
import detailStyles from "@/components/molecules/LibraryV2Detail.module.css";
import { ModelForm } from "@/components/organisms/ModelForm";
import { ModelFilterControls } from "./ModelFilterControls";
import listStyles from "@/components/organisms/LibraryCrud.module.css";

export default function ModelsRoute() {
  const [search, setSearch] = useState("");
  const [familyIdFilter, setFamilyIdFilter] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const models = useModels({ q: search });

  const filteredModels = useMemo(() => {
    let list = models.data ?? [];
    if (familyIdFilter) {
      list = list.filter((m) => m.family_id === familyIdFilter);
    }
    return list;
  }, [models.data, familyIdFilter]);

  const selected = useMemo(() => {
    const rows = models.data ?? [];
    return rows.find((model) => model.name === selectedName) ?? rows[0] ?? null;
  }, [models.data, selectedName]);

  const create = useMutation({ mutationFn: libraryApi.createModel, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ name, body }: { name: string; body: ModelUpdate }) => libraryApi.updateModel(name, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteModel, onSuccess: invalidate });

  function submit(body: ModelCreate | ModelUpdate) {
    if (mode === "create") {
      create.mutate(body as ModelCreate, {
        onSuccess: (model: Model) => {
          setSelectedName(model.name);
          setMode("detail");
        },
      });
      return;
    }
    if (selected) {
      update.mutate({ name: selected.name, body: body as ModelUpdate }, { onSuccess: () => setMode("detail") });
    }
  }

  const rows = filteredModels.map((model) => ({
    id: model.name,
    primary: model.name,
    rightMeta: model.family_id.toUpperCase(),
    tags: [model.author, model.version].filter(Boolean) as string[],
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? models.error ?? families.error;
  const total = models.data?.length ?? 0;

  const detailTitle =
    mode === "create"
      ? "New model"
      : mode === "edit" && selected
        ? `Edit · ${selected.name}`
        : selected?.name ?? "—";
  const detailTitleVariant: "mono" | "default" =
    mode === "detail" && selected ? "mono" : mode === "edit" && selected ? "mono" : "default";

  return (
    <LibraryCrud
      listTitle="Models"
      filteredCount={filteredModels.length}
      totalCount={total}
      searchPlaceholder="Search name…"
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
      detailEyebrow="Checkpoint"
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
      emptySelectionMessage="Select a model to see details"
    >
      {error && (
        <div role="alert" className={listStyles.error}>
          {String(error)}
        </div>
      )}
      {mode === "create" && (
        <ModelForm
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={create.isPending}
        />
      )}
      {mode === "edit" && selected && (
        <ModelForm
          model={selected}
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
                value: <Badge variant="accent">{selected.family_id.toUpperCase()}</Badge>,
              },
              {
                label: "Author",
                value: <span>{selected.author ?? "—"}</span>,
              },
              {
                label: "Version",
                value: <span>{selected.version ?? "—"}</span>,
              },
              {
                label: "Display name",
                value: <span>{selected.display_name || "—"}</span>,
              },
            ]}
          />
          <LibraryDetailBlock label="Prompt delta" isLast>
            {selected.description ? (
              <p className={detailStyles.desc}>{selected.description}</p>
            ) : (
              <p className={detailStyles.desc} style={{ fontStyle: "italic", color: "var(--text-subtle)" }}>
                No delta rules set.
              </p>
            )}
          </LibraryDetailBlock>
        </>
      )}
    </LibraryCrud>
  );
}
