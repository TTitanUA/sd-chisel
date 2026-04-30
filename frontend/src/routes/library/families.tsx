import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router-dom";
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
import { MarkdownView } from "@/components/molecules/MarkdownField";
import detailStyles from "@/components/molecules/LibraryV2Detail.module.css";
import { formatUpdated } from "@/lib/formatUpdated";
import listStyles from "@/components/organisms/LibraryCrud.module.css";

const BASE = "/library/families";

export default function FamiliesRoute() {
  const params = useParams<{ "*"?: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  const [search, setSearch] = useState("");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies(search);

  const splat = params["*"] ?? "";
  const segments = splat.split("/").filter(Boolean);
  const isCreate = segments[0] === "new";
  const urlId = !isCreate && segments[0] ? decodeURIComponent(segments[0]) : null;
  const isEdit = !isCreate && !!urlId && segments[1] === "edit";
  const mode: CrudMode = isCreate ? "create" : isEdit ? "edit" : "detail";

  const list = useMemo(() => families.data ?? [], [families.data]);
  const total = list.length;

  const selected = useMemo(() => {
    if (urlId) return list.find((family) => family.id === urlId) ?? null;
    return list[0] ?? null;
  }, [list, urlId]);

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

  function goDetail(id: string) {
    navigate(`${BASE}/${encodeURIComponent(id)}`);
  }
  function goList() {
    navigate(BASE);
  }
  function goEdit(id: string) {
    navigate(`${BASE}/${encodeURIComponent(id)}/edit`);
  }
  function goCreate() {
    navigate(`${BASE}/new`);
  }
  function cancelForm() {
    if (urlId) goDetail(urlId);
    else goList();
  }

  function submit(body: FamilyCreate | FamilyUpdate) {
    if (mode === "create") {
      create.mutate(body as FamilyCreate, {
        onSuccess: (family: Family) => goDetail(family.id),
      });
      return;
    }
    if (selected) {
      update.mutate(
        { id: selected.id, body: body as FamilyUpdate },
        { onSuccess: () => goDetail(selected.id) },
      );
    }
  }

  const error = create.error ?? update.error ?? remove.error ?? families.error;
  void location.pathname;

  if (mode === "create") {
    return (
      <>
        {error && (
          <div role="alert" className={listStyles.error}>
            {String(error)}
          </div>
        )}
        <FamilyForm onCancel={cancelForm} onSubmit={submit} isSaving={create.isPending} />
      </>
    );
  }

  if (mode === "edit" && selected) {
    return (
      <>
        {error && (
          <div role="alert" className={listStyles.error}>
            {String(error)}
          </div>
        )}
        <FamilyForm
          family={selected}
          onCancel={cancelForm}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      </>
    );
  }

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
      onSelect={goDetail}
      onNew={goCreate}
      detailEyebrow="Family"
      detailTitle={selected?.display_name ?? "—"}
      onEdit={selected ? () => goEdit(selected.id) : undefined}
      onDelete={
        selected
          ? () => remove.mutate(selected.id, { onSuccess: () => goList() })
          : undefined
      }
      emptySelection={!selected}
      emptySelectionMessage="Select a family to see details"
    >
      {error && (
        <div role="alert" className={listStyles.error}>
          {String(error)}
        </div>
      )}
      {selected && (
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
          {(() => {
            const i2iFilled = selected.prompt_i2i.trim() !== "";
            const t2iFilled = selected.prompt_t2i.trim() !== "";
            return (
              <>
                <LibraryDetailBlock label="Prompt guide (base)" isLast={!i2iFilled && !t2iFilled}>
                  {selected.prompt_guide
                    ? <MarkdownView value={selected.prompt_guide} />
                    : <p className={detailStyles.desc}>—</p>}
                </LibraryDetailBlock>
                {i2iFilled && (
                  <LibraryDetailBlock label="Image-to-image additions" isLast={!t2iFilled}>
                    <MarkdownView value={selected.prompt_i2i} />
                  </LibraryDetailBlock>
                )}
                {t2iFilled && (
                  <LibraryDetailBlock label="Text-to-image additions" isLast>
                    <MarkdownView value={selected.prompt_t2i} />
                  </LibraryDetailBlock>
                )}
              </>
            );
          })()}
        </>
      )}
    </LibraryCrud>
  );
}
