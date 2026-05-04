import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { useFamilies, useLoras, useModels } from "@/api/library";
import { useNodes, usePacks } from "@/api/comfy";
import { Icon } from "@/components/atoms/Icon";
import styles from "./LibraryLayout.module.css";

export function LibraryLayout({ children }: { children: ReactNode }) {
  const families = useFamilies();
  const models = useModels();
  const loras = useLoras();
  const packs = usePacks();
  const nodes = useNodes();

  const fCount = families.data?.length;
  const mCount = models.data?.length;
  const lCount = loras.data?.length;
  const comfyCount =
    packs.data === undefined && nodes.data === undefined
      ? undefined
      : (packs.data?.length ?? 0) + (nodes.data?.length ?? 0);

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
        <NavLink
          to="/library/comfy-nodes"
          className={({ isActive }) =>
            `${styles.libNavLink} ${isActive ? styles.libNavLinkActive : ""}`
          }
        >
          <span>Comfy Nodes</span>
          <span className={styles.count}>
            {comfyCount === undefined ? "—" : comfyCount}
          </span>
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
