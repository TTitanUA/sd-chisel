import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useFamilies, useLoras, useModels } from "@/api/library";
import styles from "./LibraryLayout.module.css";

export function LibraryLayout({ children }: { children: ReactNode }) {
  const families = useFamilies();
  const models = useModels();
  const loras = useLoras();

  const fCount = families.data?.length;
  const mCount = models.data?.length;
  const lCount = loras.data?.length;

  return (
    <div className={styles.libraryPage}>
      <nav className={styles.libraryNav} aria-label="Library sections">
        <div className={styles.libraryNavTitle}>Library</div>
        <NavLink
          to="/library/loras"
          className={({ isActive }) =>
            `${styles.libNavLink} ${isActive ? styles.libNavLinkActive : ""}`
          }
        >
          <span>LoRAs</span>
          <span className={styles.count}>{lCount === undefined ? "—" : lCount}</span>
        </NavLink>
        <NavLink
          to="/library/models"
          className={({ isActive }) =>
            `${styles.libNavLink} ${isActive ? styles.libNavLinkActive : ""}`
          }
        >
          <span>Models</span>
          <span className={styles.count}>{mCount === undefined ? "—" : mCount}</span>
        </NavLink>
        <NavLink
          to="/library/families"
          className={({ isActive }) =>
            `${styles.libNavLink} ${isActive ? styles.libNavLinkActive : ""}`
          }
        >
          <span>Families</span>
          <span className={styles.count}>{fCount === undefined ? "—" : fCount}</span>
        </NavLink>
      </nav>
      <div className={styles.libraryBody}>{children}</div>
    </div>
  );
}
