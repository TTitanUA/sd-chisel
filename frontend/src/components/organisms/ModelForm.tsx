import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextArea, TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import type { Family, Model, ModelCreate, ModelUpdate } from "@/api/library";

export function ModelForm({
  model,
  families,
  onCancel,
  onSubmit,
  isSaving,
}: {
  model?: Model;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: ModelCreate | ModelUpdate) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(model?.name ?? "");
  const [displayName, setDisplayName] = useState(model?.display_name ?? "");
  const [familyId, setFamilyId] = useState(model?.family_id ?? families[0]?.id ?? "");
  const [description, setDescription] = useState(model?.description ?? "");
  const [author, setAuthor] = useState(model?.author ?? "");
  const [version, setVersion] = useState(model?.version ?? "");
  const [sourceUrl, setSourceUrl] = useState(model?.source_url ?? "");

  const isEdit = Boolean(model);
  const pageTitle = isEdit && model ? `Edit · ${model.name}` : "New model";

  const canSave = displayName.trim() !== "" && familyId !== "" && (Boolean(model) || name.trim() !== "");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = {
          display_name: displayName.trim(),
          family_id: familyId,
          description: description.trim() || null,
          author: author.trim() || null,
          version: version.trim() || null,
          source_url: sourceUrl.trim() || null,
        };
        onSubmit(model ? common : { name: name.trim(), ...common });
      }}
    >
      <LibraryFormPage
        title={pageTitle}
        foot={
          <>
            <Button type="button" variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={!canSave || isSaving}
              icon={<Icon name="Check" />}
            >
              {isSaving ? "Saving…" : isEdit ? "Save changes" : "Create model"}
            </Button>
          </>
        }
      >
        <LibraryFormSection title="Identity" subtitle="Checkpoint filename and display info.">
          {!model && <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} />}
          <TextInput
            label="Display name"
            value={displayName}
            onChange={(e) => setDisplayName(e.currentTarget.value)}
          />
          <div className={libForm.grid2}>
            <TextInput label="Author" value={author} onChange={(e) => setAuthor(e.currentTarget.value)} />
            <TextInput label="Version" value={version} onChange={(e) => setVersion(e.currentTarget.value)} />
          </div>
          <TextInput
            label="Source URL"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.currentTarget.value)}
            placeholder="https://…"
          />
        </LibraryFormSection>

        <LibraryFormSection title="Family" subtitle="Which base family this checkpoint belongs to.">
          <div>
            <div className={libForm.caption}>Family</div>
            <div className={libForm.pillGroup}>
              {families.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  className={`${libForm.pill} ${familyId === f.id ? libForm.pillOn : ""}`}
                  onClick={() => setFamilyId(f.id)}
                >
                  {familyId === f.id && <Icon name="Check" size={10} />}
                  {f.display_name}
                </button>
              ))}
            </div>
            {familyId === "" && <div className={libForm.fieldError}>Select a family</div>}
          </div>
        </LibraryFormSection>

        <LibraryFormSection title="Prompt delta" subtitle="Optional rules on top of the family guide.">
          <TextArea
            label="Delta"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            placeholder="E.g. lower CFG, detail LoRA interactions…"
            rows={5}
            hint="LLM sees this when this checkpoint is selected."
          />
        </LibraryFormSection>
      </LibraryFormPage>
    </form>
  );
}
