import type { ReactNode } from "react";
import styles from "./libraryForm.module.css";

export function LibraryFormSection({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <h3 className={styles.sectionTitle}>{title}</h3>
        {subtitle && <p className={styles.sectionSub}>{subtitle}</p>}
      </div>
      <div className={styles.sectionFields}>{children}</div>
    </section>
  );
}

export function LibraryFormPage({
  title,
  children,
  foot,
}: {
  title: string;
  children: ReactNode;
  foot: ReactNode;
}) {
  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <h1 className={styles.title}>{title}</h1>
      </div>
      <div className={styles.body}>{children}</div>
      <footer className={styles.foot}>{foot}</footer>
    </div>
  );
}
