import type { ReactNode } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import styles from "./LibraryList.module.css";

export type LibraryListItem = {
  id: string;
  /** Primary line — human-readable display name */
  primary: string;
  /** Optional secondary line — technical id/filename, mono */
  secondary?: string;
  /** Right column, e.g. family code */
  rightMeta?: string;
  /** Small tag chips under primary */
  tags?: string[];
};

export function LibraryList({
  listTitle,
  filteredCount,
  totalCount,
  searchPlaceholder,
  search,
  onSearch,
  selectedId,
  items,
  onSelect,
  onNew,
  filters,
}: {
  listTitle: string;
  filteredCount: number;
  totalCount: number;
  searchPlaceholder: string;
  search: string;
  onSearch: (value: string) => void;
  selectedId: string | null;
  items: LibraryListItem[];
  onSelect: (id: string) => void;
  onNew: () => void;
  filters?: ReactNode;
}) {
  return (
    <aside className={styles.list} aria-label={`${listTitle} list`}>
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <div>
            <h2 className={styles.listTitle}>{listTitle}</h2>
            <div className={styles.subtitle}>
              {filteredCount} of {totalCount}
            </div>
          </div>
          <Button size="sm" variant="primary" type="button" icon={<Icon name="Plus" />} onClick={onNew}>
            New
          </Button>
        </div>
        <label className={styles.searchWrap}>
          <Icon name="Search" size={14} className={styles.searchIcon} aria-hidden />
          <input
            className={styles.search}
            value={search}
            placeholder={searchPlaceholder}
            onChange={(event) => onSearch(event.currentTarget.value)}
            aria-label="Search"
          />
        </label>
        {filters != null && filters !== false && <div className={styles.filtersRow}>{filters}</div>}
      </div>
      <div className={styles.rows}>
        {items.length === 0 ? (
          <div className={styles.empty} role="status">
            <Icon name="Search" size={18} aria-hidden />
            <div>No matches</div>
          </div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`${styles.row} ${item.id === selectedId ? styles.selected : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <div className={styles.rowTop}>
                <span className={styles.rowPrimary}>{item.primary}</span>
                {item.rightMeta && <span className={styles.rowRight}>{item.rightMeta}</span>}
              </div>
              {item.secondary && <div className={styles.rowSecondary}>{item.secondary}</div>}
              {item.tags && item.tags.length > 0 && (
                <div className={styles.rowTags}>
                  {item.tags.map((t) => (
                    <span key={t} className={styles.tag}>
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
