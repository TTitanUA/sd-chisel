import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import { Icon } from "@/components/atoms/Icon";
import styles from "./SettingsLayout.module.css";

const TABS = [
  { to: "/settings/lmstudio", label: "LMStudio", icon: "Server" as const },
  { to: "/settings/comfyui", label: "ComfyUI", icon: "Workflow" as const },
  { to: "/settings/privacy", label: "Privacy", icon: "Shield" as const },
];

export function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.layout}>
      <nav className={styles.nav} aria-label="Settings">
        <div className={styles.navTitle}>Settings</div>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`
            }
          >
            <Icon name={t.icon} size={12} />
            {t.label}
          </NavLink>
        ))}
      </nav>
      <main className={styles.body}>{children}</main>
    </div>
  );
}
