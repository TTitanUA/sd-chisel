import type { ReactNode } from "react";
import styles from "./LibraryV2Detail.module.css";

export function LibraryDetailMeta({ cells }: { cells: { label: string; value: ReactNode }[] }) {
  return (
    <div className={styles.meta}>
      {cells.map((cell, i) => (
        <div key={`${cell.label}-${i}`} className={styles.metaCell}>
          <span className={styles.labelCaps}>{cell.label}</span>
          <div className={styles.metaValue}>{cell.value}</div>
        </div>
      ))}
    </div>
  );
}

export function LibraryDetailBlock({
  label,
  children,
  isLast = false,
}: {
  label: string;
  children: ReactNode;
  isLast?: boolean;
}) {
  return (
    <section className={`${styles.block} ${isLast ? styles.blockLast : ""}`}>
      <div className={styles.blockLabel}>
        <span className={styles.labelCaps}>{label}</span>
      </div>
      <div className={styles.blockBody}>{children}</div>
    </section>
  );
}
