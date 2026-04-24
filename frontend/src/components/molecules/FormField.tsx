import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import styles from "./FormField.module.css";

type BaseProps = {
  label: string;
  hint?: string;
  error?: string;
  children?: ReactNode;
};

export function FormField({ label, hint, error, children }: BaseProps) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>{label}</span>
      {children}
      {hint && <span className={styles.hint}>{hint}</span>}
      {error && <span className={styles.error}>{error}</span>}
    </label>
  );
}

export function TextInput(props: BaseProps & InputHTMLAttributes<HTMLInputElement>) {
  const { label, hint, error, ...rest } = props;
  return (
    <FormField label={label} hint={hint} error={error}>
      <input className={styles.control} {...rest} />
    </FormField>
  );
}

export function TextArea(props: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { label, hint, error, ...rest } = props;
  return (
    <FormField label={label} hint={hint} error={error}>
      <textarea className={`${styles.control} ${styles.textarea}`} {...rest} />
    </FormField>
  );
}
