import { Link, Outlet, useLocation } from "react-router-dom";
import { ProjectSidebar } from "@/components/organisms/ProjectSidebar";
import styles from "./AppShell.module.css";

// TODO: wire endpoint text to live session / backend once vl_endpoint and prompt_endpoint are exposed
const PLACEHOLDER_LMSTUDIO_HOST = "localhost:1234";
const PLACEHOLDER_VL_MODEL = "qwen2-vl-7b";

export function AppShell() {
  const { pathname } = useLocation();
  const inLibrary = pathname.startsWith("/library");

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
              className={`${styles.navPill} ${!inLibrary ? styles.navPillActive : ""}`}
            >
              Workspace
            </Link>
            <Link
              to="/library/loras"
              className={`${styles.navPill} ${inLibrary ? styles.navPillActive : ""}`}
            >
              Library
            </Link>
          </nav>
        </div>
        <div className={styles.topbarSpacer} />
        <div className={styles.topbarRight}>
          <span className={styles.topbarEndpoint} title="LMStudio endpoint (placeholder)">
            <span className={styles.endpointDot} />
            {PLACEHOLDER_LMSTUDIO_HOST}
          </span>
          <span className={styles.topbarEndpoint} title="Models in use (placeholder)">
            VL · {PLACEHOLDER_VL_MODEL}
          </span>
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
