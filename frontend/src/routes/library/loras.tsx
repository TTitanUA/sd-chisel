import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router-dom";
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

const BASE = "/library/loras";

export default function LorasRoute() {
  const params = useParams<{ "*"?: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  const [search, setSearch] = useState("");
  const [familyIdFilter, setFamilyIdFilter] = useState<string | null>(null);
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const loras = useLoras({ q: search });

  const splat = params["*"] ?? "";
  const segments = splat.split("/").filter(Boolean);
  const isCreate = segments[0] === "new";
  const urlName = !isCreate && segments[0] ? decodeURIComponent(segments[0]) : null;
  const isEdit = !isCreate && !!urlName && segments[1] === "edit";
  const mode: CrudMode = isCreate ? "create" : isEdit ? "edit" : "detail";

  const filteredLoras = useMemo(() => {
    let list = loras.data ?? [];
    if (familyIdFilter) {
      list = list.filter((l) => l.family_id === familyIdFilter);
    }
    return list;
  }, [loras.data, familyIdFilter]);

  const selected = useMemo(() => {
    const rows = loras.data ?? [];
    if (urlName) return rows.find((l) => l.name === urlName) ?? null;
    return rows[0] ?? null;
  }, [loras.data, urlName]);

  const create = useMutation({ mutationFn: libraryApi.createLora, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ name, body }: { name: string; body: LoraUpdate }) => libraryApi.updateLora(name, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteLora, onSuccess: invalidate });

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

  function submit(body: LoraCreate | LoraUpdate) {
    if (mode === "create") {
      create.mutate(body as LoraCreate, {
        onSuccess: (lora: Lora) => goDetail(lora.name),
      });
      return;
    }
    if (selected) {
      update.mutate(
        { name: selected.name, body: body as LoraUpdate },
        { onSuccess: () => goDetail(selected.name) },
      );
    }
  }

  const rows = filteredLoras.map((lora) => ({
    id: lora.name,
    primary: lora.display_name || lora.name,
    secondary: lora.display_name ? lora.name : undefined,
    rightMeta: lora.family_id.toUpperCase(),
    tags: lora.tags.slice(0, 2),
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? loras.error ?? families.error;
  const total = loras.data?.length ?? 0;

  void location.pathname;

  if (mode === "create") {
    return (
      <>
        {error && (
          <div role="alert" className={listStyles.error}>
            {String(error)}
          </div>
        )}
        <LoraForm
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
        <LoraForm
          lora={selected}
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
      listTitle="LoRA"
      filteredCount={filteredLoras.length}
      totalCount={total}
      searchPlaceholder="Search name, tag, trigger…"
      search={search}
      onSearch={setSearch}
      items={rows}
      selectedId={selected?.name ?? null}
      onSelect={goDetail}
      onNew={goCreate}
      detailEyebrow="LoRA"
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
      emptySelectionMessage="Select a LoRA to see details"
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
                label: "Index",
                value: (
                  <Badge variant={selected.is_indexed ? "accent" : "neutral"}>
                    {selected.is_indexed ? "Indexed" : "Not indexed"}
                  </Badge>
                ),
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
