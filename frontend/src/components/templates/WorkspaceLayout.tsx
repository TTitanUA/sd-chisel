import type { ReactNode } from "react";
import styles from "./WorkspaceLayout.module.css";

export function WorkspaceLayout({ children }: { children: ReactNode }) {
  return <div className={styles.layout}>{children}</div>;
}
