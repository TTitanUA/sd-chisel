import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router-dom";
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

const BASE = "/library/models";

export default function ModelsRoute() {
  const params = useParams<{ "*"?: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  const [search, setSearch] = useState("");
  const [familyIdFilter, setFamilyIdFilter] = useState<string | null>(null);
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const models = useModels({ q: search });

  const splat = params["*"] ?? "";
  const segments = splat.split("/").filter(Boolean);
  const isCreate = segments[0] === "new";
  const urlName = !isCreate && segments[0] ? decodeURIComponent(segments[0]) : null;
  const isEdit = !isCreate && !!urlName && segments[1] === "edit";
  const mode: CrudMode = isCreate ? "create" : isEdit ? "edit" : "detail";

  const filteredModels = useMemo(() => {
    let list = models.data ?? [];
    if (familyIdFilter) {
      list = list.filter((m) => m.family_id === familyIdFilter);
    }
    return list;
  }, [models.data, familyIdFilter]);

  const selected = useMemo(() => {
    const rows = models.data ?? [];
    if (urlName) return rows.find((model) => model.name === urlName) ?? null;
    return rows[0] ?? null;
  }, [models.data, urlName]);

  const create = useMutation({ mutationFn: libraryApi.createModel, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ name, body }: { name: string; body: ModelUpdate }) => libraryApi.updateModel(name, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteModel, onSuccess: invalidate });

  function goDetail(name: string) {
    navigate(`${BASE}/${encodeURIComponent(name)}`);
  }
  function goList() {
    navigate(BASE);
  }
  function goEdit(name: string) {
    navigate(`${BASE}/${encodeURIComponent(name)}/edit`);
  }
  function goCreate() {
    navigate(`${BASE}/new`);
  }
  function cancelForm() {
    if (urlName) goDetail(urlName);
    else goList();
  }

  function submit(body: ModelCreate | ModelUpdate) {
    if (mode === "create") {
      create.mutate(body as ModelCreate, {
        onSuccess: (model: Model) => goDetail(model.name),
      });
      return;
    }
    if (selected) {
      update.mutate(
        { name: selected.name, body: body as ModelUpdate },
        { onSuccess: () => goDetail(selected.name) },
      );
    }
  }

  const rows = filteredModels.map((model) => ({
    id: model.name,
    primary: model.display_name || model.name,
    secondary: model.display_name ? model.name : undefined,
    rightMeta: model.family_id.toUpperCase(),
    tags: [model.author, model.version].filter(Boolean) as string[],
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? models.error ?? families.error;
  const total = models.data?.length ?? 0;

  // Avoid unused-warning when location is referenced only for re-renders
  void location.pathname;

  if (mode === "create") {
    return (
      <>
        {error && (
          <div role="alert" className={listStyles.error}>
            {String(error)}
          </div>
        )}
        <ModelForm
          families={familyRows}
          onCancel={cancelForm}
          onSubmit={submit}
          isSaving={create.isPending}
        />
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
        <ModelForm
          model={selected}
          families={familyRows}
          onCancel={cancelForm}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      </>
    );
  }

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
      onSelect={goDetail}
      onNew={goCreate}
      detailEyebrow="Checkpoint"
      detailTitle={selected?.display_name || selected?.name || "—"}
      detailSubtitle={selected?.display_name ? selected.name : undefined}
      onEdit={selected ? () => goEdit(selected.name) : undefined}
      onDelete={
        selected
          ? () => remove.mutate(selected.name, { onSuccess: () => goList() })
          : undefined
      }
      filters={
        <ModelFilterControls
          families={familyRows}
          familyId={familyIdFilter}
          onChange={setFamilyIdFilter}
        />
      }
      emptySelection={!selected}
      emptySelectionMessage="Select a model to see details"
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
