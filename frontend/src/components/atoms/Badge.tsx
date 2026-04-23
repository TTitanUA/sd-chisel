import type { ReactNode } from "react";
import styles from "./Badge.module.css";

type Props = {
  variant?: "neutral" | "accent";
  icon?: ReactNode;
  children: ReactNode;
};

export function Badge({ variant = "neutral", icon, children }: Props) {
  const cls = [styles.badge, variant === "accent" ? styles.accent : null].filter(Boolean).join(" ");
  return (
    <span className={cls}>
      {icon}
      {children}
    </span>
  );
}
