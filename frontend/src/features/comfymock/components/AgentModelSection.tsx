/** Per-agent model picker and sampling params editor.
 *
 *  The LMStudio model list comes from
 *  `/api/settings/lmstudio/models` (cached via TanStack Query). The
 *  picker filters out hidden / disabled models so the user only sees
 *  what the workspace can actually call. Sampling params are stored
 *  on `agent.model_params` — a free-form `Record<string, unknown>`.
 *  We pull out the four values the LLM emulator (and eventually the
 *  real run path) cares about and leave anything else under
 *  `model_params` untouched, so other features that stash bytes
 *  there — input slots in particular — survive a save here.
 *
 *  See docs/comfy-agents-ui-mock-plan.md.
 */
import { useEffect, useMemo, useState } from "react";
import { useLmModels } from "@/api/settings";
import { useUpdateAgent, type Agent } from "@/api/comfy";
import { useComfyMock } from "../state/useComfyMock";
import styles from "./AgentModelSection.module.css";

type SamplingParams = {
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
  seed: number | null;
};

const DEFAULTS: SamplingParams = {
  temperature: 0.7,
  top_p: 1.0,
  max_tokens: 1024,
  seed: null,
};

export function AgentModelSection({ agent }: { agent: Agent }) {
  const { session } = useComfyMock();
  const update = useUpdateAgent(session.id);
  const models = useLmModels();

  // Keep "everything else" the rest of the app might have written
  // into model_params (notably the input-slots blob), so a save here
  // doesn't blow it away.
  const [draftName, setDraftName] = useState<string | null>(agent.model_name);
  const [draftParams, setDraftParams] = useState<SamplingParams>(
    () => extractSampling(agent.model_params),
  );

  // Keep local state in sync when the upstream agent changes (e.g.
  // another tab edited the same record). Only re-apply server values
  // when the local draft equals what was last seen — see the same
  // pattern in useSlotDraft.
  useEffect(() => {
    setDraftName((prev) => (prev === agent.model_name ? prev : agent.model_name));
    setDraftParams((prev) => {
      const fresh = extractSampling(agent.model_params);
      return JSON.stringify(prev) === JSON.stringify(fresh) ? prev : fresh;
    });
  }, [agent.model_name, agent.model_params]);

  const dirty = useMemo(() => {
    if (draftName !== agent.model_name) return true;
    const current = extractSampling(agent.model_params);
    return JSON.stringify(current) !== JSON.stringify(draftParams);
  }, [draftName, draftParams, agent.model_name, agent.model_params]);

  function patch(p: Partial<SamplingParams>) {
    setDraftParams((prev) => ({ ...prev, ...p }));
  }

  function save() {
    // Merge the four sampling fields into the existing model_params
    // bag — preserves anything else that lives there (input slots,
    // future tool config, etc.).
    const base = (agent.model_params ?? {}) as Record<string, unknown>;
    const merged: Record<string, unknown> = {
      ...base,
      temperature: draftParams.temperature,
      top_p: draftParams.top_p,
      max_tokens: draftParams.max_tokens,
      seed: draftParams.seed,
    };
    // Strip null sampling values to keep the payload tidy — null means
    // "let the model decide / use default" and is the same as omitting.
    for (const k of ["temperature", "top_p", "max_tokens", "seed"]) {
      if (merged[k] === null) delete merged[k];
    }
    update.mutate({
      agentId: agent.id,
      body: {
        model_name: draftName,
        model_params: Object.keys(merged).length === 0 ? null : merged,
      },
    });
  }

  const visibleModels = (models.data ?? []).filter(
    (m) => !m.hidden && m.enabled,
  );
  const selectedModel = visibleModels.find((m) => m.name === draftName) ?? null;

  return (
    <section className={styles.section}>
      <header className={styles.head}>
        <span className={styles.title}>Model</span>
        {dirty && (
          <button
            type="button"
            className={styles.saveBtn}
            disabled={update.isPending}
            onClick={save}
          >
            {update.isPending ? "Saving…" : "Save model"}
          </button>
        )}
      </header>

      <div className={styles.row}>
        <label className={styles.fieldLabel}>Name</label>
        <select
          className={styles.input}
          value={draftName ?? ""}
          onChange={(e) =>
            setDraftName(e.currentTarget.value === "" ? null : e.currentTarget.value)
          }
          disabled={models.isLoading}
        >
          <option value="">{models.isLoading ? "Loading…" : "(none — use workspace default)"}</option>
          {visibleModels.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
              {(m.vision || m.tool_use || m.reasoning) && " — "}
              {[m.vision && "vision", m.tool_use && "tools", m.reasoning && "reasoning"]
                .filter(Boolean)
                .join(", ")}
            </option>
          ))}
        </select>
      </div>

      {selectedModel && (
        <div className={styles.caps}>
          {selectedModel.vision && (
            <span className={styles.cap}>vision-capable</span>
          )}
          {selectedModel.tool_use && <span className={styles.cap}>tool use</span>}
          {selectedModel.reasoning && <span className={styles.cap}>reasoning</span>}
          {!selectedModel.vision &&
            !selectedModel.tool_use &&
            !selectedModel.reasoning && (
              <span className={styles.capDim}>plain text-only model</span>
            )}
        </div>
      )}

      <div className={styles.params}>
        <SliderField
          label="Temperature"
          value={draftParams.temperature}
          defaultValue={DEFAULTS.temperature!}
          min={0}
          max={2}
          step={0.05}
          onChange={(v) => patch({ temperature: v })}
        />
        <SliderField
          label="Top-p"
          value={draftParams.top_p}
          defaultValue={DEFAULTS.top_p!}
          min={0}
          max={1}
          step={0.01}
          onChange={(v) => patch({ top_p: v })}
        />
        <NumberField
          label="Max tokens"
          value={draftParams.max_tokens}
          defaultValue={DEFAULTS.max_tokens!}
          step={64}
          min={32}
          max={32768}
          onChange={(v) => patch({ max_tokens: v })}
        />
        <NumberField
          label="Seed"
          value={draftParams.seed}
          placeholder="random"
          step={1}
          min={0}
          max={2147483647}
          onChange={(v) => patch({ seed: v })}
        />
      </div>

      {update.isError && (
        <div className={styles.err}>{(update.error as Error).message}</div>
      )}
    </section>
  );
}

// --- params helpers -----------------------------------------------------

function extractSampling(raw: Record<string, unknown> | null): SamplingParams {
  if (!raw) return { temperature: null, top_p: null, max_tokens: null, seed: null };
  return {
    temperature: numberOrNull(raw.temperature),
    top_p: numberOrNull(raw.top_p),
    max_tokens: intOrNull(raw.max_tokens),
    seed: intOrNull(raw.seed),
  };
}

function numberOrNull(v: unknown): number | null {
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  return null;
}

function intOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isInteger(v)) return v;
  return null;
}

function SliderField({
  label,
  value,
  defaultValue,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number | null;
  defaultValue: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number | null) => void;
}) {
  const effective = value ?? defaultValue;
  const isDefault = value === null;
  // Floating-point sliders return values like 0.6999999988 — round to
  // the step's decimal precision so the input renders cleanly.
  const decimals = step.toString().split(".")[1]?.length ?? 0;
  const round = (n: number) =>
    decimals > 0 ? Number(n.toFixed(decimals)) : Math.round(n);
  return (
    <div className={styles.paramRow}>
      <label className={styles.paramLabel}>
        {label}
        {isDefault && <span className={styles.paramDefault}>(default)</span>}
      </label>
      <div className={styles.paramCtl}>
        <input
          type="range"
          className={styles.slider}
          min={min}
          max={max}
          step={step}
          value={effective}
          onChange={(e) => onChange(round(parseFloat(e.currentTarget.value)))}
        />
        <input
          type="number"
          className={styles.paramNum}
          min={min}
          max={max}
          step={step}
          value={round(effective)}
          onChange={(e) => {
            const n = parseFloat(e.currentTarget.value);
            if (!Number.isNaN(n)) onChange(round(n));
          }}
        />
        {!isDefault && (
          <button
            type="button"
            className={styles.paramReset}
            onClick={() => onChange(null)}
            title="Restore default"
          >
            ↺
          </button>
        )}
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  defaultValue,
  placeholder,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number | null;
  defaultValue?: number;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number | null) => void;
}) {
  return (
    <div className={styles.paramRow}>
      <label className={styles.paramLabel}>
        {label}
        {value === null && (
          <span className={styles.paramDefault}>
            {defaultValue !== undefined ? "(default)" : ""}
          </span>
        )}
      </label>
      <div className={styles.paramCtl}>
        <input
          type="number"
          className={styles.paramNum}
          placeholder={placeholder ?? (defaultValue !== undefined ? String(defaultValue) : "")}
          min={min}
          max={max}
          step={step}
          value={value ?? ""}
          onChange={(e) => {
            const raw = e.currentTarget.value;
            if (raw === "") {
              onChange(null);
              return;
            }
            const n = parseFloat(raw);
            if (!Number.isNaN(n)) onChange(n);
          }}
        />
        {value !== null && (
          <button
            type="button"
            className={styles.paramReset}
            onClick={() => onChange(null)}
            title="Use default"
          >
            ↺
          </button>
        )}
      </div>
    </div>
  );
}
