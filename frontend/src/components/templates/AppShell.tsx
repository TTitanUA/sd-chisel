import { Link, Outlet, useLocation } from "react-router-dom";
import { ProjectSidebar } from "@/components/organisms/ProjectSidebar";
import { useLmStudioConfig } from "@/api/settings";
import styles from "./AppShell.module.css";

export function AppShell() {
  const { pathname } = useLocation();
  const inLibrary = pathname.startsWith("/library");
  const inSettings = pathname.startsWith("/settings");
  const cfg = useLmStudioConfig();

  const host = cfg.data?.base_url
    ? cfg.data.base_url.replace(/^https?:\/\//, "").replace(/\/v1\/?$/, "")
    : "(no endpoint)";
  const dot = cfg.data?.configured ? styles.endpointDotOn : styles.endpointDotOff;

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.topbarLeft}>
          <div className={styles.brand}>
            <span className={styles.brandGlyph}>sd</span>
            <span className={styles.brandName}>sd-chisel</span>
          </div>
          <nav className={styles.topbarNav} aria-label="App mode">
            <Link
              to="/"
              className={`${styles.navPill} ${!inLibrary && !inSettings ? styles.navPillActive : ""}`}
            >
              Workspace
            </Link>
            <Link
              to="/library/loras"
              className={`${styles.navPill} ${inLibrary ? styles.navPillActive : ""}`}
            >
              Library
            </Link>
            <Link
              to="/settings/lmstudio"
              className={`${styles.navPill} ${inSettings ? styles.navPillActive : ""}`}
            >
              Settings
            </Link>
          </nav>
        </div>
        <div className={styles.topbarSpacer} />
        <div className={styles.topbarRight}>
          <Link
            to="/settings/lmstudio"
            className={styles.topbarEndpoint}
            title={
              cfg.data?.configured
                ? `LMStudio · ${cfg.data.base_url}`
                : "LMStudio endpoint not configured — click to set up"
            }
          >
            <span className={`${styles.endpointDot} ${dot}`} />
            {host}
          </Link>
        </div>
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
