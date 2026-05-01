import { useCallback, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { AssistantPane } from "@/components/molecules/AssistantPane";
import { streamAssist, type AssistFieldsSnapshot } from "@/api/assist";
import type { Family, FamilyCreate, FamilyUpdate } from "@/api/library";

const FAMILY_TOOL_LABELS: Record<string, string> = {
  update_prompt_guide: "updating base guide",
  update_prompt_i2i: "updating i2i guide",
  update_prompt_t2i: "updating t2i guide",
};

export function FamilyForm({
  family,
  onCancel,
  onSubmit,
  isSaving,
}: {
  family?: Family;
  onCancel: () => void;
  onSubmit: (body: FamilyCreate | FamilyUpdate) => void;
  isSaving: boolean;
}) {
  const [id, setId] = useState(family?.id ?? "");
  const [displayName, setDisplayName] = useState(family?.display_name ?? "");
  const [promptGuide, setPromptGuide] = useState(family?.prompt_guide ?? "");
  const [promptI2i, setPromptI2i] = useState(family?.prompt_i2i ?? "");
  const [promptT2i, setPromptT2i] = useState(family?.prompt_t2i ?? "");
  const [showAssistant, setShowAssistant] = useState(false);

  const isEdit = Boolean(family);
  const pageTitle = isEdit && family ? `Edit · ${family.display_name}` : "New family";

  const canSave =
    displayName.trim() !== "" &&
    promptGuide.trim() !== "" &&
    (Boolean(family) || id.trim() !== "");

  const handleArtifact = useCallback((field: string, content: string) => {
    if (field === "prompt_guide") setPromptGuide(content);
    else if (field === "prompt_i2i") setPromptI2i(content);
    else if (field === "prompt_t2i") setPromptT2i(content);
  }, []);

  const getCurrentState = useCallback(
    (): AssistFieldsSnapshot => ({
      prompt_guide: promptGuide,
      prompt_i2i: promptI2i,
      prompt_t2i: promptT2i,
    }),
    [promptGuide, promptI2i, promptT2i],
  );

  const form = (
    <form
      className={showAssistant ? libForm.formMain : libForm.formShell}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = {
          display_name: displayName.trim(),
          prompt_guide: promptGuide.trim(),
          prompt_i2i: promptI2i.trim(),
          prompt_t2i: promptT2i.trim(),
        };
        onSubmit(family ? common : { id: id.trim(), ...common });
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
              Families
            </button>
            <Icon name="ChevronRight" size={10} aria-hidden />
            <span className={libForm.breadcrumbCurrent}>
              {isEdit ? family?.display_name : "New family"}
            </span>
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
            <Button
              type="submit"
              variant="primary"
              disabled={!canSave || isSaving}
              icon={<Icon name="Check" />}
            >
              {isSaving ? "Saving…" : isEdit ? "Save changes" : "Create family"}
            </Button>
          </>
        }
      >
        <LibraryFormSection title="Identity" subtitle="ID in code and the display name in the UI.">
          <TextInput
            label="ID"
            hint="slug, lowercase"
            value={id}
            placeholder="sdxl"
            onChange={(e) => setId(e.currentTarget.value)}
            disabled={isEdit}
          />
          <TextInput
            label="Display name"
            value={displayName}
            placeholder="SDXL"
            onChange={(e) => setDisplayName(e.currentTarget.value)}
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Prompt guide (base)"
          subtitle="Shared rules for this family. The downstream LLM sees this in every session."
        >
          <MarkdownField
            label="Content"
            value={promptGuide}
            onChange={setPromptGuide}
            hint="Output language, tag syntax, quality tokens, LoRA conventions, negative prompt rules."
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Image-to-image additions"
          subtitle="Optional. Shown only when the session is i2i."
        >
          <MarkdownField
            label="Content (optional)"
            value={promptI2i}
            onChange={setPromptI2i}
            hint="What to preserve from the source, transformation language, denoising guidance."
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Text-to-image additions"
          subtitle="Optional. Shown only when the session is t2i."
        >
          <MarkdownField
            label="Content (optional)"
            value={promptT2i}
            onChange={setPromptT2i}
            hint="Scene composition, subject and background description, framing/camera."
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
        streamFn={streamAssist}
        toolLabels={FAMILY_TOOL_LABELS}
        placeholder="Describe the family or paste docs…"
        emptyMessage="Paste documentation or describe the model family to get started."
      />
    </div>
  );
}
