import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import type { Family, Model, ModelCreate, ModelUpdate } from "@/api/library";

const SLUG_RE = /^[a-zA-Z0-9_.-]+$/;

export function ModelForm({
  model,
  families,
  onCancel,
  onSubmit,
  isSaving,
  onRename,
  isRenaming,
  renameError,
}: {
  model?: Model;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: ModelCreate | ModelUpdate) => void;
  isSaving: boolean;
  onRename?: (newName: string) => void;
  isRenaming?: boolean;
  renameError?: string | null;
}) {
  const [name, setName] = useState(model?.name ?? "");
  const [displayName, setDisplayName] = useState(model?.display_name ?? "");
  const [familyId, setFamilyId] = useState(model?.family_id ?? families[0]?.id ?? "");
  const [description, setDescription] = useState(model?.description ?? "");
  const [author, setAuthor] = useState(model?.author ?? "");
  const [version, setVersion] = useState(model?.version ?? "");
  const [sourceUrl, setSourceUrl] = useState(model?.source_url ?? "");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(model?.name ?? "");

  const isEdit = Boolean(model);
  const editLabel = model?.display_name || model?.name || "";
  const pageTitle = isEdit ? `Edit · ${editLabel}` : "New model";

  const canSave = displayName.trim() !== "" && familyId !== "" && (Boolean(model) || name.trim() !== "");

  return (
    <form
      className={libForm.formShell}
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
        breadcrumb={
          <>
            <button type="button" className={libForm.breadcrumbButton} onClick={onCancel}>
              Library
            </button>
            <Icon name="ChevronRight" size={10} aria-hidden />
            <button type="button" className={libForm.breadcrumbButton} onClick={onCancel}>
              Models
            </button>
            <Icon name="ChevronRight" size={10} aria-hidden />
            <span className={libForm.breadcrumbCurrent}>{isEdit ? editLabel : "New model"}</span>
          </>
        }
        foot={
          <>
            <Button type="button" variant="ghost" onClick={onCancel}>
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
          <div>
            <TextInput
              label="Name"
              hint={isEdit ? "filename — locked, used as primary key" : "filename without .safetensors"}
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              disabled={isEdit}
            />
            {isEdit && onRename && !renameOpen && (
              <button
                type="button"
                className={libForm.renameToggle}
                onClick={() => {
                  setRenameValue(model?.name ?? "");
                  setRenameOpen(true);
                }}
              >
                Rename…
              </button>
            )}
            {isEdit && onRename && renameOpen && (
              <>
                <div className={libForm.renameRow}>
                  <TextInput
                    label="New filename slug"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.currentTarget.value)}
                    placeholder={model?.name ?? ""}
                    autoFocus
                  />
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={
                      isRenaming ||
                      renameValue.trim() === "" ||
                      renameValue.trim() === model?.name ||
                      !SLUG_RE.test(renameValue.trim())
                    }
                    onClick={() => onRename(renameValue.trim())}
                  >
                    {isRenaming ? "Renaming…" : "Save"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setRenameOpen(false)}
                    disabled={isRenaming}
                  >
                    Cancel
                  </Button>
                </div>
                {renameError && (
                  <div role="alert" className={libForm.renameError}>
                    {renameError}
                  </div>
                )}
              </>
            )}
          </div>
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
          <MarkdownField
            label="Delta"
            value={description}
            onChange={setDescription}
            hint="LLM sees this when this checkpoint is selected."
          />
        </LibraryFormSection>
      </LibraryFormPage>
    </form>
  );
}
