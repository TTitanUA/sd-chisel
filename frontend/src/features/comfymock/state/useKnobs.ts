/** CSS-variable knobs for layout exploration. Each variant declares
 *  the knobs it wants to expose; KnobsStrip renders sliders + numeric
 *  inputs that write to the same `--var-name` on `document.documentElement`.
 *
 *  Values persist to localStorage keyed by (variant, knobName) so a
 *  variant's tunables survive page reloads.
 *
 *  See docs/comfy-agents-ui-mock-plan.md. */
import { useCallback, useEffect, useMemo, useState } from "react";

export type KnobSpec = {
  /** CSS variable name including leading `--`. */
  cssVar: string;
  /** Human label shown in KnobsStrip. */
  label: string;
  /** Initial value. */
  default: number;
  min: number;
  max: number;
  step: number;
  /** Suffix appended when writing to the CSS variable (e.g. `"px"`,
   *  `"%"`, `"fr"`). Defaults to `"px"`. */
  unit?: string;
};

const STORAGE_PREFIX = "comfymock:knob:";

function storageKey(variant: string, cssVar: string): string {
  return `${STORAGE_PREFIX}${variant}:${cssVar}`;
}

function readKnob(variant: string, spec: KnobSpec): number {
  try {
    const raw = localStorage.getItem(storageKey(variant, spec.cssVar));
    if (!raw) return spec.default;
    const parsed = parseFloat(raw);
    if (Number.isNaN(parsed)) return spec.default;
    return Math.max(spec.min, Math.min(spec.max, parsed));
  } catch {
    return spec.default;
  }
}

function applyKnob(spec: KnobSpec, value: number): void {
  const unit = spec.unit ?? "px";
  document.documentElement.style.setProperty(spec.cssVar, `${value}${unit}`);
}

export type KnobBindings = {
  values: Record<string, number>;
  setValue: (cssVar: string, value: number) => void;
  reset: () => void;
  specs: KnobSpec[];
  variant: string;
};

export function useKnobs(variant: string, specs: KnobSpec[]): KnobBindings {
  const initial = useMemo(() => {
    const out: Record<string, number> = {};
    for (const s of specs) out[s.cssVar] = readKnob(variant, s);
    return out;
  }, [variant, specs]);

  const [values, setValues] = useState<Record<string, number>>(initial);

  // Re-seed when the variant or spec list changes.
  useEffect(() => {
    setValues(initial);
  }, [initial]);

  // Apply CSS variables on mount and when values change.
  useEffect(() => {
    for (const s of specs) {
      applyKnob(s, values[s.cssVar] ?? s.default);
    }
    // Cleanup: leave the variables in place on unmount so the layout
    // doesn't flash to defaults during route transitions; explicit
    // reset clears them via the action below.
  }, [specs, values]);

  const setValue = useCallback(
    (cssVar: string, value: number) => {
      const spec = specs.find((s) => s.cssVar === cssVar);
      if (!spec) return;
      const clamped = Math.max(spec.min, Math.min(spec.max, value));
      setValues((prev) => ({ ...prev, [cssVar]: clamped }));
      try {
        localStorage.setItem(storageKey(variant, cssVar), String(clamped));
      } catch {
        /* ignore quota */
      }
    },
    [specs, variant],
  );

  const reset = useCallback(() => {
    const fresh: Record<string, number> = {};
    for (const s of specs) {
      fresh[s.cssVar] = s.default;
      try {
        localStorage.removeItem(storageKey(variant, s.cssVar));
      } catch {
        /* ignore */
      }
    }
    setValues(fresh);
  }, [specs, variant]);

  return { values, setValue, reset, specs, variant };
}
