import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { Slider } from "@/components/molecules/Slider";
import { TagInput } from "@/components/molecules/TagInput";
import type { Family, Lora, LoraCreate, LoraUpdate } from "@/api/library";

export function LoraForm({
  lora,
  families,
  onCancel,
  onSubmit,
  isSaving,
}: {
  lora?: Lora;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: LoraCreate | LoraUpdate) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(lora?.name ?? "");
  const [displayName, setDisplayName] = useState(lora?.display_name ?? "");
  const [description, setDescription] = useState(lora?.description ?? "");
  const [tags, setTags] = useState<string[]>(lora?.tags ?? []);
  const [triggerWords, setTriggerWords] = useState<string[]>(lora?.trigger_words ?? []);
  const [familyId, setFamilyId] = useState(lora?.family_id ?? families[0]?.id ?? "");
  const [recommendedWeight, setRecommendedWeight] = useState(lora?.recommended_weight ?? 0.75);
  const [author, setAuthor] = useState(lora?.author ?? "");
  const [version, setVersion] = useState(lora?.version ?? "");
  const [sourceUrl, setSourceUrl] = useState(lora?.source_url ?? "");

  const isEdit = Boolean(lora);
  const editLabel = lora?.display_name || lora?.name || "";
  const pageTitle = isEdit ? `Edit · ${editLabel}` : "New LoRA";

  const canSave =
    displayName.trim() !== "" &&
    description.trim() !== "" &&
    familyId !== "" &&
    (Boolean(lora) || name.trim() !== "");

  return (
    <form
      className={libForm.formShell}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = {
          display_name: displayName.trim(),
          description: description.trim(),
          tags,
          trigger_words: triggerWords,
          family_id: familyId,
          recommended_weight: recommendedWeight,
          author: author.trim() || null,
          version: version.trim() || null,
          source_url: sourceUrl.trim() || null,
        };
        onSubmit(lora ? common : { name: name.trim(), ...common });
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
              LoRAs
            </button>
            <Icon name="ChevronRight" size={10} aria-hidden />
            <span className={libForm.breadcrumbCurrent}>{isEdit ? editLabel : "New LoRA"}</span>
          </>
        }
        foot={
          <>
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!canSave || isSaving} icon={<Icon name="Check" />}>
              {isSaving ? "Saving…" : isEdit ? "Save changes" : "Create LoRA"}
            </Button>
          </>
        }
      >
        <LibraryFormSection
          title="Identity"
          subtitle="Filename and display info. LLM uses description when choosing LoRAs."
        >
          <TextInput
            label="Name"
            hint={isEdit ? "filename — locked, used as primary key" : "filename without .safetensors"}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            disabled={isEdit}
          />
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

        <LibraryFormSection title="Family" subtitle="Which base family this LoRA is for.">
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
          <Slider
            label="weight"
            min={0}
            max={2}
            step={0.05}
            value={recommendedWeight}
            onChange={setRecommendedWeight}
            hint="Typical 0.5–0.9 depending on the asset."
          />
        </LibraryFormSection>

        <LibraryFormSection title="Taxonomy" subtitle="Tags and trigger words — used by retriever.">
          <TagInput label="Tags" value={tags} onChange={setTags} placeholder="add tag + Enter..." />
          <TagInput
            label="Trigger words"
            value={triggerWords}
            onChange={setTriggerWords}
            placeholder="add trigger + Enter..."
            variant="code"
          />
        </LibraryFormSection>

        <LibraryFormSection title="Description" subtitle="Markdown. LLM sees this verbatim.">
          <MarkdownField
            label="Content"
            value={description}
            onChange={setDescription}
            hint="Be specific: quality, incompatibilities, and when to use."
          />
        </LibraryFormSection>
      </LibraryFormPage>
    </form>
  );
}
