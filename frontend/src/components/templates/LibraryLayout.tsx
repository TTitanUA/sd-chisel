import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useFamilies, useLoras, useModels } from "@/api/library";
import { Icon } from "@/components/atoms/Icon";
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
        <div className={styles.navSpacer} />
        <Link to="/" className={styles.backLink}>
          <Icon name="ChevronLeft" size={10} strokeWidth={2} />
          Back
        </Link>
      </nav>
      <div className={styles.libraryBody}>{children}</div>
    </div>
  );
}
