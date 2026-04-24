import { Outlet } from "react-router-dom";
import { useHealth } from "@/api/health";
import { ProjectSidebar } from "@/components/organisms/ProjectSidebar";
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
      <div className={styles.sidebar}>
        <ProjectSidebar />
      </div>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
