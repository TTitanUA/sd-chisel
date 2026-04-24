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
import { LibraryDetailBlock, LibraryDetailMeta } from "@/components/molecules/LibraryV2Detail";
import detailStyles from "@/components/molecules/LibraryV2Detail.module.css";
import { formatUpdated } from "@/lib/formatUpdated";
import listStyles from "@/components/organisms/LibraryCrud.module.css";

export default function FamiliesRoute() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies(search);

  const list = useMemo(() => families.data ?? [], [families.data]);
  const total = list.length;

  const selected = useMemo(() => {
    return list.find((family) => family.id === selectedId) ?? list[0] ?? null;
  }, [list, selectedId]);

  const create = useMutation({ mutationFn: libraryApi.createFamily, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: FamilyUpdate }) => libraryApi.updateFamily(id, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteFamily, onSuccess: invalidate });

  const rows = list.map((family) => ({
    id: family.id,
    primary: family.display_name,
    tags: [family.id],
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

  const detailTitle =
    mode === "create"
      ? "New family"
      : mode === "edit" && selected
        ? `Edit · ${selected.display_name}`
        : selected?.display_name ?? "—";
  const detailTitleVariant: "mono" | "default" =
    mode === "detail" && selected ? "default" : mode === "edit" && selected ? "default" : "default";

  return (
    <LibraryCrud
      listTitle="Families"
      filteredCount={total}
      totalCount={total}
      searchPlaceholder="Search display name, id…"
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
      detailTitle={detailTitle}
      detailTitleVariant={detailTitleVariant}
      onEdit={selected && mode === "detail" ? () => setMode("edit") : undefined}
      onDelete={
        selected && mode === "detail"
          ? () => remove.mutate(selected.id, { onSuccess: () => setSelectedId(null) })
          : undefined
      }
      emptySelection={mode === "detail" && !selected}
      emptySelectionMessage="Select a family to see details"
    >
      {error && (
        <div role="alert" className={listStyles.error}>
          {String(error)}
        </div>
      )}
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
          <LibraryDetailMeta
            cells={[
              {
                label: "ID",
                value: <code className="ds-code">{selected.id}</code>,
              },
              {
                label: "Display name",
                value: <span>{selected.display_name}</span>,
              },
              {
                label: "Updated",
                value: <span>{formatUpdated(selected.updated_at)}</span>,
              },
            ]}
          />
          <LibraryDetailBlock label="Prompt guide" isLast>
            <p className={detailStyles.desc}>{selected.prompt_guide}</p>
          </LibraryDetailBlock>
        </>
      )}
    </LibraryCrud>
  );
}
