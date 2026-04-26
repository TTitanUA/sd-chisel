import { Badge } from "@/components/atoms/Badge";
import { Slider } from "@/components/molecules/Slider";
import type { LoraSpec } from "@/api/prompts";
import type { Lora } from "@/api/library";

export type LoraRowKind = "pinned" | "retrieved" | "picked" | "unknown";

export function classifyLora(
  spec: LoraSpec,
  refs: {
    knownByName: Record<string, Lora>;
    pinnedNames: Set<string>;
    retrievedNames: Set<string>;
  },
): LoraRowKind {
  if (!(spec.name in refs.knownByName)) return "unknown";
  if (refs.pinnedNames.has(spec.name)) return "pinned";
  if (refs.retrievedNames.has(spec.name)) return "retrieved";
  return "picked";
}

export function PromptLoraRow({
  spec,
  kind,
  triggers,
  weight,
  onWeightChange,
}: {
  spec: LoraSpec;
  kind: LoraRowKind;
  triggers: string[];
  weight: number;
  onWeightChange: (next: number) => void;
}) {
  const variant = kind === "unknown" ? "accent" : "neutral";
  const label = kind === "unknown" ? "⚠ unknown" : kind;
  return (
    <div data-kind={kind} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Badge variant={variant}>{label}</Badge>
        <code style={{ fontFamily: "var(--font-mono)" }}>{spec.name}</code>
        {triggers.length > 0 && (
          <span style={{ color: "var(--text-subtle)", fontSize: 12 }}>
            ({triggers.join(", ")})
          </span>
        )}
      </div>
      <Slider
        label="weight"
        min={-2}
        max={2}
        step={0.05}
        value={weight}
        onChange={onWeightChange}
      />
    </div>
  );
}
