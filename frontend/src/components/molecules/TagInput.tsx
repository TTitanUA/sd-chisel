import { useState, type KeyboardEvent } from "react";
import { Icon } from "@/components/atoms/Icon";
import styles from "./TagInput.module.css";

export function TagInput({
  label,
  value,
  onChange,
  placeholder,
  variant = "chip",
  hint,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  variant?: "chip" | "code";
  hint?: string;
}) {
  const [draft, setDraft] = useState("");

  function addToken(raw: string) {
    const token = raw.trim();
    if (token && !value.includes(token)) {
      onChange([...value, token]);
    }
    setDraft("");
  }

  function removeToken(token: string) {
    onChange(value.filter((item) => item !== token));
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addToken(draft);
    }
    if (event.key === "Backspace" && draft === "" && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  }

  return (
    <label className={styles.field}>
      <span className={styles.label}>{label}</span>
      <div className={styles.box}>
        {value.map((token) =>
          variant === "code" ? (
            <code key={token} className={`ds-code ${styles.codeChip}`}>
              {token}
              <button
                type="button"
                className={styles.remove}
                onClick={() => removeToken(token)}
                aria-label={`Remove ${token}`}
              >
                <Icon name="X" size={8} aria-hidden />
              </button>
            </code>
          ) : (
            <span key={token} className="ds-chip">
              {token}
              <button
                type="button"
                className="ds-chip-x"
                onClick={() => removeToken(token)}
                aria-label={`Remove ${token}`}
              >
                <Icon name="X" size={9} aria-hidden />
              </button>
            </span>
          ),
        )}
        <input
          className={styles.input}
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onBlur={() => addToken(draft)}
          onKeyDown={handleKeyDown}
        />
      </div>
      {hint && <span className={styles.hint}>{hint}</span>}
    </label>
  );
}
