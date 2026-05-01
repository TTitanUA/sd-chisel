import { usePrivacy, useSetPrivacy } from "@/api/settings";
import styles from "./privacy.module.css";

export default function PrivacyRoute() {
  const privacy = usePrivacy();
  const setPrivacy = useSetPrivacy();
  const showHidden = privacy.data?.show_hidden ?? false;

  return (
    <div className={styles.page}>
      <section className={styles.section}>
        <h2 className={styles.h}>Privacy</h2>
        <p className={styles.sub}>
          Items marked as hidden disappear from sidebars and lists. Toggle this
          on to reveal them temporarily without changing each item.
        </p>

        <label className={styles.row}>
          <input
            type="checkbox"
            checked={showHidden}
            disabled={privacy.isLoading || setPrivacy.isPending}
            onChange={(e) => setPrivacy.mutate({ show_hidden: e.currentTarget.checked })}
          />
          <span>
            <span className={styles.label}>Show hidden items</span>
            <span className={styles.help}>
              When off, items with the <code>hidden</code> flag are filtered out.
            </span>
          </span>
        </label>
      </section>
    </div>
  );
}
