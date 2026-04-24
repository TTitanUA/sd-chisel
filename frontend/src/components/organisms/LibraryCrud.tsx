import type { ReactNode } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { LibraryList, type LibraryListItem } from "@/components/molecules/LibraryList";
import styles from "./LibraryCrud.module.css";

export type CrudMode = "detail" | "create" | "edit";

export function LibraryCrud({
  title,
  count,
  search,
  onSearch,
  items,
  selectedId,
  onSelect,
  onNew,
  mode,
  detailTitle,
  detailEyebrow,
  onEdit,
  onDelete,
  children,
}: {
  title: string;
  count: number;
  search: string;
  onSearch: (value: string) => void;
  items: LibraryListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  mode: CrudMode;
  detailTitle: string;
  detailEyebrow: string;
  onEdit?: () => void;
  onDelete?: () => void;
  children: ReactNode;
}) {
  return (
    <div className={styles.page}>
      <LibraryList
        title={title}
        count={count}
        search={search}
        onSearch={onSearch}
        selectedId={selectedId}
        items={items}
        onSelect={onSelect}
        onNew={onNew}
      />
      <section className={styles.detail}>
        <div className={styles.detailHead}>
          <div>
            <div className={styles.eyebrow}>{detailEyebrow}</div>
            <h1 className={styles.title}>{detailTitle}</h1>
          </div>
          {mode === "detail" && (
            <div className={styles.actions}>
              {onDelete && (
                <Button size="sm" icon={<Icon name="Trash2" />} onClick={onDelete}>
                  Delete
                </Button>
              )}
              {onEdit && (
                <Button size="sm" variant="primary" onClick={onEdit}>
                  Edit
                </Button>
              )}
            </div>
          )}
        </div>
        <div className={mode === "detail" ? styles.body : styles.form}>{children}</div>
      </section>
    </div>
  );
}
