/** Devtools strip — sliders + numeric inputs for every CSS variable
 *  the active variant declares. Toggle with the button in the
 *  ComfyMock header (or `?knobs=1`). See
 *  docs/comfy-agents-ui-mock-plan.md. */
import type { KnobBindings } from "../state/useKnobs";
import styles from "./KnobsStrip.module.css";

export function KnobsStrip({ knobs }: { knobs: KnobBindings }) {
  return (
    <div className={styles.strip}>
      <div className={styles.title}>
        layout knobs · variant <code>{knobs.variant}</code>
      </div>
      <div className={styles.list}>
        {knobs.specs.map((spec) => {
          const value = knobs.values[spec.cssVar] ?? spec.default;
          return (
            <div key={spec.cssVar} className={styles.knob}>
              <label className={styles.knobLabel}>
                {spec.label}
                <code className={styles.var}>{spec.cssVar}</code>
              </label>
              <div className={styles.controls}>
                <input
                  type="range"
                  min={spec.min}
                  max={spec.max}
                  step={spec.step}
                  value={value}
                  onChange={(e) =>
                    knobs.setValue(spec.cssVar, parseFloat(e.target.value))
                  }
                  className={styles.slider}
                />
                <input
                  type="number"
                  min={spec.min}
                  max={spec.max}
                  step={spec.step}
                  value={value}
                  onChange={(e) =>
                    knobs.setValue(spec.cssVar, parseFloat(e.target.value))
                  }
                  className={styles.number}
                />
                <span className={styles.unit}>{spec.unit ?? "px"}</span>
              </div>
            </div>
          );
        })}
      </div>
      <button type="button" className={styles.reset} onClick={knobs.reset}>
        reset
      </button>
    </div>
  );
}
