import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import type { Family, FamilyCreate, FamilyUpdate } from "@/api/library";

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

  const isEdit = Boolean(family);
  const pageTitle = isEdit && family ? `Edit · ${family.display_name}` : "New family";

  const canSave = displayName.trim() !== "" && promptGuide.trim() !== "" && (Boolean(family) || id.trim() !== "");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = { display_name: displayName.trim(), prompt_guide: promptGuide.trim() };
        onSubmit(family ? common : { id: id.trim(), ...common });
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
              {isSaving ? "Saving…" : isEdit ? "Save changes" : "Create family"}
            </Button>
          </>
        }
      >
        <LibraryFormSection title="Identity" subtitle="ID in code and the display name in the UI.">
          {!family && (
            <TextInput
              label="ID (slug, lowercase)"
              value={id}
              placeholder="sdxl"
              onChange={(e) => setId(e.currentTarget.value)}
            />
          )}
          <TextInput
            label="Display name"
            value={displayName}
            placeholder="SDXL"
            onChange={(e) => setDisplayName(e.currentTarget.value)}
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Prompt guide"
          subtitle="Base rules for this family. LLM sees this in every session."
        >
          <MarkdownField
            label="Content"
            value={promptGuide}
            onChange={setPromptGuide}
            hint="Syntax, quality tags, token style, and how LoRAs interact."
          />
        </LibraryFormSection>
      </LibraryFormPage>
    </form>
  );
}
