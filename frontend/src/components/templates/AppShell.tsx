import { NavLink, Outlet } from "react-router-dom";
import { useHealth } from "@/api/health";
import styles from "./AppShell.module.css";

export function AppShell() {
  const health = useHealth();
  const status = health.isError ? "down" : health.data?.status === "ok" ? "ok" : "pending";
  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <span className={styles.brand}>sd-chisel</span>
        <span className={styles.healthDot} data-status={status}>
          backend {status}
        </span>
      </header>
      <aside className={styles.sidebar}>
        <nav className={styles.sidebarNav}>
          <NavLink
            to="/projects/scrapyard/sessions/default"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Workspace
          </NavLink>
          <NavLink
            to="/library/families"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Library — Families
          </NavLink>
          <NavLink
            to="/library/models"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Library — Models
          </NavLink>
          <NavLink
            to="/library/loras"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Library — LoRAs
          </NavLink>
        </nav>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
