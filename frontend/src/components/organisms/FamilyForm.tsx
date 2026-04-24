import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { TextInput } from "@/components/molecules/FormField";
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
      {!family && (
        <TextInput
          label="ID"
          value={id}
          placeholder="sdxl"
          onChange={(event) => setId(event.currentTarget.value)}
        />
      )}
      <TextInput
        label="Display name"
        value={displayName}
        placeholder="SDXL"
        onChange={(event) => setDisplayName(event.currentTarget.value)}
      />
      <MarkdownField
        label="Prompt guide"
        value={promptGuide}
        onChange={setPromptGuide}
        hint="LLM sees this verbatim for every session using this family."
      />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!canSave || isSaving}>
          {isSaving ? "Saving..." : "Save"}
        </Button>
      </div>
    </form>
  );
}
