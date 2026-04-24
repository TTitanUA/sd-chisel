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
import { LoraForm } from "@/components/organisms/LoraForm";

export default function LorasRoute() {
  const [search, setSearch] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const loras = useLoras({ q: search });

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

  const rows = (loras.data ?? []).map((lora) => ({
    id: lora.name,
    title: lora.display_name,
    meta: `${lora.family_compat.join(", ")} | ${lora.tags.join(", ")}`,
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? loras.error ?? families.error;

  return (
    <LibraryCrud
      title="LoRAs"
      count={loras.data?.length ?? 0}
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
      detailTitle={mode === "create" ? "New LoRA" : selected?.display_name ?? "No LoRA selected"}
      onEdit={selected ? () => setMode("edit") : undefined}
      onDelete={
        selected ? () => remove.mutate(selected.name, { onSuccess: () => setSelectedName(null) }) : undefined
      }
    >
      {error && <div role="alert">{String(error)}</div>}
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
          <p>
            <strong>Name:</strong> {selected.name}
          </p>
          <p>
            <strong>Weight:</strong> {selected.recommended_weight ?? "none"}
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {selected.family_compat.map((family) => (
              <Badge key={family}>{family}</Badge>
            ))}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {selected.tags.map((tag) => (
              <Badge key={tag} variant="accent">
                {tag}
              </Badge>
            ))}
          </div>
          <p>
            <strong>Triggers:</strong> {selected.trigger_words.join(", ") || "none"}
          </p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{selected.description}</pre>
        </>
      )}
    </LibraryCrud>
  );
}
