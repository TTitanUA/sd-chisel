import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { useLoras } from "@/api/library";
import type { Lora } from "@/api/library";
import {
  usePrompts,
  type GeneratedPrompt,
  type Intent,
  type LoraSpec,
  type Prompt,
  type RetrievedIntent,
} from "@/api/prompts";
import type { Session } from "@/api/sessions";
import { useIsReindexing } from "@/api/tasks";
import { GenerateModal } from "./GenerateModal";
import { classifyLora, PromptLoraRow } from "./PromptLoraRow";
import styles from "./PromptPane.module.css";

export function PromptPane({ session }: { session: Session }) {
  const prompts = usePrompts(session.id);
  const loras = useLoras();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [debugOpen, setDebugOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const isReindexing = useIsReindexing();
  const mainSourceAnalysis =
    session.source_images.find((i) => i.is_main)?.analysis ?? null;
  const list = prompts.data ?? [];
  const head: Prompt | null = list[0] ?? null;
  const visible: Prompt | null =
    selectedId == null ? head : list.find((p) => p.id === selectedId) ?? head;

  // Per-row weight overrides; reset whenever the visible prompt changes.
  const [weights, setWeights] = useState<Record<string, number>>({});
  const visibleId = visible?.id ?? null;
  useEffect(() => {
    setWeights({});
  }, [visibleId]);
  const effectiveWeight = (spec: LoraSpec) =>
    weights[spec.name] ?? spec.weight;

  const knownByName = useMemo<Record<string, Lora>>(() => {
    const out: Record<string, Lora> = {};
    for (const l of loras.data ?? []) out[l.name] = l;
    return out;
  }, [loras.data]);

  const pinnedNames = useMemo(
    () => new Set(session.pinned_loras.map((p) => p.lora_name)),
    [session.pinned_loras],
  );
  const retrievedNames = useMemo(
    () =>
      new Set(
        (visible?.retrieved ?? []).flatMap((r) => r.results.map((h) => h.name)),
      ),
    [visible],
  );

  const loraString = useMemo(
    () =>
      (visible?.prompt.loras ?? [])
        .map((l) => `<lora:${l.name}:${effectiveWeight(l).toFixed(2)}>`)
        .join(" "),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visible, weights],
  );

  const fullString = useMemo(() => {
    if (!visible) return "";
    const p = visible.prompt;
    const parts = [p.positive, loraString].filter(Boolean);
    return parts.join("\n\n") + (p.negative ? `\n\nNEGATIVE:\n${p.negative}` : "");
  }, [visible, loraString]);

  function copy(text: string) {
    if (!text) return;
    void navigator.clipboard?.writeText(text);
  }

  return (
    <div className={styles.pane} aria-label="Prompt pane">
      <div className={styles.copyRow}>
        <Button
          size="sm"
          variant="primary"
          icon={<Icon name="Sparkles" size={12} />}
          onClick={() => setModalOpen(true)}
          disabled={!mainSourceAnalysis || isReindexing}
          title={
            !mainSourceAnalysis
              ? "Run Analyze on the main source image first"
              : isReindexing
                ? "LoRA index is updating — try again in a moment"
                : visible
                  ? "Regenerate"
                  : "Generate prompt"
          }
        >
          {visible ? "Regenerate" : "Generate"}
        </Button>
      </div>

      <GenerateModal
        session={session}
        open={modalOpen}
        onOpenChange={setModalOpen}
      />

      {!visible && (
        <div className={styles.empty}>
          No prompt yet. Click <b>Generate</b> to produce one from the current
          chat + source analysis.
        </div>
      )}

      {visible && (
        <>
          <PositiveSection prompt={visible.prompt} onCopy={copy} />
          {visible.prompt.negative !== null && (
            <NegativeSection prompt={visible.prompt} onCopy={copy} />
          )}
          <LoraSection
            prompt={visible.prompt}
            knownByName={knownByName}
            pinnedNames={pinnedNames}
            retrievedNames={retrievedNames}
            weights={weights}
            onWeightChange={(name, w) =>
              setWeights((prev) => ({ ...prev, [name]: w }))
            }
          />
          <div className={styles.copyRow}>
            <Button size="sm" onClick={() => copy(loraString)} disabled={!loraString}>
              Copy LoRA string
            </Button>
            <Button size="sm" onClick={() => copy(fullString)} disabled={!fullString}>
              Copy all
            </Button>
          </div>

          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span>Debug</span>
              <Button size="sm" variant="ghost" onClick={() => setDebugOpen((v) => !v)}>
                {debugOpen ? "hide" : "show"}
              </Button>
            </div>
            {debugOpen && (
              <pre className={styles.debug}>
                {formatDebug(visible.intents, visible.retrieved)}
              </pre>
            )}
          </div>
        </>
      )}

      {list.length > 1 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>History</div>
          <div className={styles.history}>
            {list.map((p) => (
              <button
                key={p.id}
                className={styles.historyItem}
                aria-selected={(visible?.id ?? -1) === p.id}
                onClick={() => setSelectedId(p.id)}
              >
                #{p.id} · {new Date(p.created_at * 1000).toLocaleTimeString()} ·{" "}
                {p.prompt.loras.length} lora
                {p.prompt.loras.length === 1 ? "" : "s"}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PositiveSection({
  prompt, onCopy,
}: { prompt: GeneratedPrompt; onCopy: (s: string) => void }) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span>Positive</span>
        <Button size="sm" variant="ghost" onClick={() => onCopy(prompt.positive)}>
          copy
        </Button>
      </div>
      <textarea readOnly className={styles.textarea} value={prompt.positive} />
    </div>
  );
}

function NegativeSection({
  prompt, onCopy,
}: { prompt: GeneratedPrompt; onCopy: (s: string) => void }) {
  const value = prompt.negative ?? "";
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span>Negative</span>
        <Button size="sm" variant="ghost" onClick={() => onCopy(value)}>
          copy
        </Button>
      </div>
      <textarea readOnly className={styles.textarea} value={value} />
    </div>
  );
}

function LoraSection({
  prompt,
  knownByName,
  pinnedNames,
  retrievedNames,
  weights,
  onWeightChange,
}: {
  prompt: GeneratedPrompt;
  knownByName: Record<string, Lora>;
  pinnedNames: Set<string>;
  retrievedNames: Set<string>;
  weights: Record<string, number>;
  onWeightChange: (name: string, next: number) => void;
}) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>LoRAs ({prompt.loras.length})</div>
      <div className={styles.loraList}>
        {prompt.loras.map((spec) => {
          const kind = classifyLora(spec, {
            knownByName, pinnedNames, retrievedNames,
          });
          const triggers = knownByName[spec.name]?.trigger_words ?? [];
          return (
            <PromptLoraRow
              key={spec.name}
              spec={spec}
              kind={kind}
              triggers={triggers}
              weight={weights[spec.name] ?? spec.weight}
              onWeightChange={(w) => onWeightChange(spec.name, w)}
            />
          );
        })}
      </div>
    </div>
  );
}

function formatDebug(
  intents: Intent[] | null, retrieved: RetrievedIntent[] | null,
): string {
  if (!intents) return "(no intent debug — older prompt row)";
  const lines: string[] = [];
  for (const i of intents) {
    lines.push(`• ${i.kind}: ${i.query}`);
    const ri = retrieved?.find((r) => r.intent_query === i.query);
    if (ri) {
      for (const h of ri.results) {
        lines.push(`    - ${h.name}  (d=${h.distance.toFixed(3)})`);
      }
    }
  }
  return lines.join("\n");
}
