import type { ReactNode } from "react";
import styles from "./LibraryLayout.module.css";

export function LibraryLayout({ children }: { children: ReactNode }) {
  return <div className={styles.layout}>{children}</div>;
}
