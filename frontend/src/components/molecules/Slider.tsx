import { useId, type ReactNode } from "react";
import styles from "./Slider.module.css";

export function Slider({
  label,
  min,
  max,
  step,
  value,
  onChange,
  unit = "",
  hint,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (next: number) => void;
  unit?: string;
  hint?: ReactNode;
}) {
  const labelId = useId();
  const pct = ((value - min) / (max - min)) * 100;
  const zeroPct = ((0 - min) / (max - min)) * 100;
  const fillLeft = Math.min(zeroPct, pct);
  const fillWidth = Math.abs(pct - zeroPct);

  return (
    <div className="ds-slider">
      <div className="ds-slider-row">
        <span className="ds-slider-label" id={labelId}>
          {label}
        </span>
        <span className="ds-slider-value">
          {value.toFixed(2)}
          {unit}
        </span>
      </div>
      <div className="ds-slider-track">
        <div className="ds-slider-tick" style={{ left: `${zeroPct}%` }} />
        <div
          className="ds-slider-fill"
          style={{
            left: `${fillLeft}%`,
            width: `${fillWidth}%`,
          }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.currentTarget.value))}
          aria-labelledby={labelId}
        />
        <div className="ds-slider-thumb" style={{ left: `${pct}%` }} />
      </div>
      {hint != null && hint !== "" && <span className={styles.hint}>{hint}</span>}
    </div>
  );
}
