import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { TextArea, TextInput } from "@/components/molecules/FormField";
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
      {!model && (
        <TextInput label="Name" value={name} onChange={(event) => setName(event.currentTarget.value)} />
      )}
      <TextInput
        label="Display name"
        value={displayName}
        onChange={(event) => setDisplayName(event.currentTarget.value)}
      />
      <label>
        <span>Family</span>
        <select
          value={familyId}
          onChange={(event) => setFamilyId(event.currentTarget.value)}
        >
          {families.map((family) => (
            <option key={family.id} value={family.id}>
              {family.display_name}
            </option>
          ))}
        </select>
      </label>
      <TextArea
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.currentTarget.value)}
      />
      <TextInput label="Author" value={author} onChange={(event) => setAuthor(event.currentTarget.value)} />
      <TextInput label="Version" value={version} onChange={(event) => setVersion(event.currentTarget.value)} />
      <TextInput
        label="Source URL"
        value={sourceUrl}
        onChange={(event) => setSourceUrl(event.currentTarget.value)}
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
