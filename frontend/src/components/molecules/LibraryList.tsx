import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import styles from "./LibraryList.module.css";

export type LibraryListItem = {
  id: string;
  title: string;
  meta?: string;
};

export function LibraryList({
  title,
  count,
  search,
  onSearch,
  selectedId,
  items,
  onSelect,
  onNew,
}: {
  title: string;
  count: number;
  search: string;
  onSearch: (value: string) => void;
  selectedId: string | null;
  items: LibraryListItem[];
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className={styles.list}>
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <h2 className={styles.title}>{title}</h2>
          <Button size="sm" variant="primary" icon={<Icon name="Plus" />} onClick={onNew}>
            New
          </Button>
        </div>
        <input
          className={styles.search}
          value={search}
          placeholder={`Search ${title.toLowerCase()}...`}
          onChange={(event) => onSearch(event.currentTarget.value)}
        />
        <span className={styles.rowMeta}>{count} total</span>
      </div>
      <div className={styles.rows}>
        {items.length === 0 ? (
          <div className={styles.empty}>No matches</div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`${styles.row} ${item.id === selectedId ? styles.selected : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <span className={styles.rowName}>{item.title}</span>
              {item.meta && <span className={styles.rowMeta}>{item.meta}</span>}
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
