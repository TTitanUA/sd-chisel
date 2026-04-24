import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
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
import { ModelForm } from "@/components/organisms/ModelForm";

export default function ModelsRoute() {
  const [search, setSearch] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const models = useModels({ q: search });

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

  const rows = (models.data ?? []).map((model) => ({
    id: model.name,
    title: model.display_name,
    meta: model.family_id,
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? models.error ?? families.error;

  return (
    <LibraryCrud
      title="Models"
      count={models.data?.length ?? 0}
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
      detailEyebrow="Model"
      detailTitle={mode === "create" ? "New model" : selected?.display_name ?? "No model selected"}
      onEdit={selected ? () => setMode("edit") : undefined}
      onDelete={
        selected ? () => remove.mutate(selected.name, { onSuccess: () => setSelectedName(null) }) : undefined
      }
    >
      {error && <div role="alert">{String(error)}</div>}
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
          <p>
            <strong>Name:</strong> {selected.name}
          </p>
          <p>
            <strong>Family:</strong> {selected.family_id}
          </p>
          <p>{selected.description ?? "No description"}</p>
        </>
      )}
    </LibraryCrud>
  );
}
