import { useCallback, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { AssistantPane, type ImportSource } from "@/components/molecules/AssistantPane";
import { streamLoraAssist, type LoraAssistFieldsSnapshot } from "@/api/assist";
import { Slider } from "@/components/molecules/Slider";
import { TagInput } from "@/components/molecules/TagInput";
import { libraryApi, type Family, type Lora, type LoraCreate, type LoraUpdate } from "@/api/library";
import { ApiError } from "@/api/client";
import civitaiIcon from "@/assets/civitai-icon.png";

const SLUG_RE = /^[a-zA-Z0-9_.-]+$/;

const LORA_TOOL_LABELS: Record<string, string> = {
  update_name: "setting name",
  update_display_name: "setting display name",
  update_description: "updating description",
  update_tags: "updating tags",
  update_trigger_words: "updating trigger words",
  update_family_id: "setting family",
  update_recommended_weight: "setting weight",
  update_author: "setting author",
  update_version: "setting version",
  update_source_url: "setting source URL",
};

function formatCivitaiImportMessage(
  ref: string,
  d: Awaited<ReturnType<typeof libraryApi.importLoraFromCivitai>>,
): string {
  const tags = d.tags.length ? d.tags.join(", ") : "(none)";
  const triggers = d.trigger_words.length ? d.trigger_words.join(", ") : "(none)";
  const desc = d.description.trim() || "(empty)";
  return [
    "Import this LoRA's metadata from Civitai. Apply your strict rules — strip all links, citations, marketing prose, version notes, software/setup instructions, and download stats. Keep ONLY practical prompting guidance in the description.",
    "",
    `Reference: ${ref}`,
    `AIR: ${d.air || "(not provided)"}`,
    `Civitai type: ${d.model_type || "(unknown)"}`,
    `Base model: ${d.base_model || "(unknown)"}`,
    "",
    `Filename (no extension): ${d.name || "(empty)"}`,
    `Display name: ${d.display_name || "(empty)"}`,
    `Author: ${d.author || "(empty)"}`,
    `Version: ${d.version || "(empty)"}`,
    `Source URL: ${d.source_url || "(empty)"}`,
    `Tags: ${tags}`,
    `Trigger words: ${triggers}`,
    "",
    "Raw description (markdown converted from HTML):",
    desc,
    "",
    "Use the appropriate update_* tools to fill the form fields per your strict rules. The base_model is just a hint to help pick a family from the available list.",
  ].join("\n");
}

const CIVITAI_SOURCE: ImportSource = {
  id: "civitai",
  label: "Civitai.com AIR",
  iconUrl: civitaiIcon,
  inputLabel: "AIR identifier or URL",
  inputPlaceholder: "urn:air:flux2:lora:civitai:2436859@2760799",
  inputHint: "Example: urn:air:flux2:lora:civitai:2436859@2760799",
  fetchAndFormat: async (ref) => {
    try {
      const data = await libraryApi.importLoraFromCivitai(ref);
      return formatCivitaiImportMessage(ref, data);
    } catch (err) {
      if (err instanceof ApiError) {
        let detail = err.body;
        try {
          const parsed = JSON.parse(err.body) as { detail?: string };
          if (parsed.detail) detail = parsed.detail;
        } catch { /* not JSON */ }
        throw new Error(detail);
      }
      throw err;
    }
  },
};

const LORA_IMPORT_SOURCES: ImportSource[] = [CIVITAI_SOURCE];

export function LoraForm({
  lora,
  families,
  onCancel,
  onSubmit,
  isSaving,
  onRename,
  isRenaming,
  renameError,
}: {
  lora?: Lora;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: LoraCreate | LoraUpdate) => void;
  isSaving: boolean;
  onRename?: (newName: string) => void;
  isRenaming?: boolean;
  renameError?: string | null;
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
  const [showAssistant, setShowAssistant] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(lora?.name ?? "");

  const isEdit = Boolean(lora);
  const editLabel = lora?.display_name || lora?.name || "";
  const pageTitle = isEdit ? `Edit · ${editLabel}` : "New LoRA";

  const canSave =
    displayName.trim() !== "" &&
    description.trim() !== "" &&
    familyId !== "" &&
    (Boolean(lora) || name.trim() !== "");

  const handleArtifact = useCallback((field: string, content: string) => {
    switch (field) {
      case "name":
        if (!isEdit) setName(content);
        break;
      case "display_name":
        setDisplayName(content);
        break;
      case "description":
        setDescription(content);
        break;
      case "tags":
        try {
          const parsed = JSON.parse(content);
          if (Array.isArray(parsed)) setTags(parsed.map(String));
        } catch { /* ignore malformed */ }
        break;
      case "trigger_words":
        try {
          const parsed = JSON.parse(content);
          if (Array.isArray(parsed)) setTriggerWords(parsed.map(String));
        } catch { /* ignore malformed */ }
        break;
      case "family_id":
        if (families.some((f) => f.id === content)) setFamilyId(content);
        break;
      case "recommended_weight": {
        const n = Number(content);
        if (!Number.isNaN(n) && n >= -2 && n <= 2) setRecommendedWeight(n);
        break;
      }
      case "author":
        setAuthor(content);
        break;
      case "version":
        setVersion(content);
        break;
      case "source_url":
        setSourceUrl(content);
        break;
    }
  }, [isEdit, families]);

  const getCurrentState = useCallback(
    (): LoraAssistFieldsSnapshot => ({
      name,
      display_name: displayName,
      description,
      tags,
      trigger_words: triggerWords,
      family_id: familyId,
      recommended_weight: recommendedWeight,
      author,
      version,
      source_url: sourceUrl,
      available_families: families.map((f) => ({ id: f.id, display_name: f.display_name })),
      is_edit_mode: isEdit,
    }),
    [name, displayName, description, tags, triggerWords, familyId, recommendedWeight, author, version, sourceUrl, families, isEdit],
  );

  const form = (
    <form
      className={showAssistant ? libForm.formMain : libForm.formShell}
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
            <Button
              type="button"
              variant="ghost"
              size="sm"
              icon={<Icon name="MessageSquare" size={12} />}
              onClick={() => setShowAssistant((v) => !v)}
            >
              {showAssistant ? "Hide assistant" : "Assistant"}
            </Button>
            <div style={{ flex: 1 }} />
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
                  setRenameValue(lora?.name ?? "");
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
                    placeholder={lora?.name ?? ""}
                    autoFocus
                  />
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={
                      isRenaming ||
                      renameValue.trim() === "" ||
                      renameValue.trim() === lora?.name ||
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

  if (!showAssistant) return form;

  return (
    <div className={libForm.formWithAssistant}>
      {form}
      <AssistantPane
        onArtifact={handleArtifact}
        getCurrentState={getCurrentState}
        streamFn={streamLoraAssist}
        toolLabels={LORA_TOOL_LABELS}
        placeholder="Describe the LoRA or paste docs…"
        emptyMessage="Paste documentation, describe the LoRA, or use Import to pull metadata from Civitai."
        importSources={LORA_IMPORT_SOURCES}
      />
    </div>
  );
}
