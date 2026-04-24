import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Badge } from "@/components/atoms/Badge";
import { TextInput } from "@/components/molecules/FormField";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { TextListInput } from "@/components/molecules/TextListInput";
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
  const [familyCompat, setFamilyCompat] = useState<string[]>(lora?.family_compat ?? []);
  const [recommendedWeight, setRecommendedWeight] = useState(
    lora?.recommended_weight === null || lora?.recommended_weight === undefined
      ? ""
      : String(lora.recommended_weight),
  );
  const [author, setAuthor] = useState(lora?.author ?? "");
  const [version, setVersion] = useState(lora?.version ?? "");
  const [sourceUrl, setSourceUrl] = useState(lora?.source_url ?? "");

  const canSave =
    displayName.trim() !== "" &&
    description.trim() !== "" &&
    familyCompat.length > 0 &&
    (Boolean(lora) || name.trim() !== "");

  function toggleFamily(id: string) {
    setFamilyCompat((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const weight = recommendedWeight.trim() === "" ? null : Number(recommendedWeight);
        const common = {
          display_name: displayName.trim(),
          description: description.trim(),
          tags,
          trigger_words: triggerWords,
          family_compat: familyCompat,
          recommended_weight: Number.isFinite(weight) ? weight : null,
          author: author.trim() || null,
          version: version.trim() || null,
          source_url: sourceUrl.trim() || null,
        };
        onSubmit(lora ? common : { name: name.trim(), ...common });
      }}
    >
      {!lora && <TextInput label="Name" value={name} onChange={(event) => setName(event.currentTarget.value)} />}
      <TextInput
        label="Display name"
        value={displayName}
        onChange={(event) => setDisplayName(event.currentTarget.value)}
      />
      <MarkdownField
        label="Description"
        value={description}
        onChange={setDescription}
        hint="Markdown. LLM sees this when picking LoRAs."
      />
      <TextListInput label="Tags" value={tags} onChange={setTags} placeholder="detail, light, portrait" />
      <TextListInput
        label="Trigger words"
        value={triggerWords}
        onChange={setTriggerWords}
        placeholder="cinematic light, rim light"
      />
      <div>
        <div style={{ marginBottom: 8 }}>Family compatibility</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {families.map((family) => (
            <button type="button" key={family.id} onClick={() => toggleFamily(family.id)}>
              <Badge variant={familyCompat.includes(family.id) ? "accent" : "neutral"}>
                {family.display_name}
              </Badge>
            </button>
          ))}
        </div>
      </div>
      <TextInput
        label="Recommended weight"
        type="number"
        step="0.05"
        min="-2"
        max="2"
        value={recommendedWeight}
        onChange={(event) => setRecommendedWeight(event.currentTarget.value)}
      />
      <TextInput label="Author" value={author} onChange={(event) => setAuthor(event.currentTarget.value)} />
      <TextInput label="Version" value={version} onChange={(event) => setVersion(event.currentTarget.value)} />
      <TextInput label="Source URL" value={sourceUrl} onChange={(event) => setSourceUrl(event.currentTarget.value)} />
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
