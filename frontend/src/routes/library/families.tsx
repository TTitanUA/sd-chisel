import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  libraryApi,
  useFamilies,
  useLibraryInvalidation,
  type Family,
  type FamilyCreate,
  type FamilyUpdate,
} from "@/api/library";
import { FamilyForm } from "@/components/organisms/FamilyForm";
import { LibraryCrud, type CrudMode } from "@/components/organisms/LibraryCrud";

export default function FamiliesRoute() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies(search);

  const selected = useMemo(() => {
    const rows = families.data ?? [];
    return rows.find((family) => family.id === selectedId) ?? rows[0] ?? null;
  }, [families.data, selectedId]);

  const create = useMutation({ mutationFn: libraryApi.createFamily, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: FamilyUpdate }) => libraryApi.updateFamily(id, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteFamily, onSuccess: invalidate });

  const rows = (families.data ?? []).map((family) => ({
    id: family.id,
    title: family.display_name,
    meta: family.id,
  }));

  function submit(body: FamilyCreate | FamilyUpdate) {
    if (mode === "create") {
      create.mutate(body as FamilyCreate, {
        onSuccess: (family: Family) => {
          setSelectedId(family.id);
          setMode("detail");
        },
      });
      return;
    }
    if (selected) {
      update.mutate(
        { id: selected.id, body: body as FamilyUpdate },
        { onSuccess: () => setMode("detail") },
      );
    }
  }

  const error = create.error ?? update.error ?? remove.error ?? families.error;

  return (
    <LibraryCrud
      title="Families"
      count={families.data?.length ?? 0}
      search={search}
      onSearch={setSearch}
      items={rows}
      selectedId={selected?.id ?? null}
      onSelect={(id) => {
        setSelectedId(id);
        setMode("detail");
      }}
      onNew={() => setMode("create")}
      mode={mode}
      detailEyebrow="Family"
      detailTitle={mode === "create" ? "New family" : selected?.display_name ?? "No family selected"}
      onEdit={selected ? () => setMode("edit") : undefined}
      onDelete={
        selected
          ? () => remove.mutate(selected.id, { onSuccess: () => setSelectedId(null) })
          : undefined
      }
    >
      {error && <div role="alert">{String(error)}</div>}
      {mode === "create" && (
        <FamilyForm onCancel={() => setMode("detail")} onSubmit={submit} isSaving={create.isPending} />
      )}
      {mode === "edit" && selected && (
        <FamilyForm
          family={selected}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      )}
      {mode === "detail" && selected && (
        <>
          <p>
            <strong>ID:</strong> {selected.id}
          </p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{selected.prompt_guide}</pre>
        </>
      )}
    </LibraryCrud>
  );
}
