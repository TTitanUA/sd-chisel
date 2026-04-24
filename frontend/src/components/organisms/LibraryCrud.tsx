import type { ReactNode } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { LibraryList, type LibraryListItem } from "@/components/molecules/LibraryList";
import styles from "./LibraryCrud.module.css";

export type CrudMode = "detail" | "create" | "edit";

export function LibraryCrud({
  listTitle,
  filteredCount,
  totalCount,
  searchPlaceholder,
  search,
  onSearch,
  items,
  selectedId,
  onSelect,
  onNew,
  mode,
  detailTitle,
  detailEyebrow,
  detailTitleVariant = "mono",
  onEdit,
  onDelete,
  filters,
  emptySelection,
  emptySelectionMessage,
  children,
}: {
  listTitle: string;
  filteredCount: number;
  totalCount: number;
  searchPlaceholder?: string;
  search: string;
  onSearch: (value: string) => void;
  items: LibraryListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  mode: CrudMode;
  detailTitle: string;
  detailEyebrow: string;
  /** Detail page title uses monospace (filename / id) */
  detailTitleVariant?: "mono" | "default";
  onEdit?: () => void;
  onDelete?: () => void;
  filters?: ReactNode;
  /** When in detail mode but nothing selected, show centered hint */
  emptySelection?: boolean;
  emptySelectionMessage?: string;
  children: ReactNode;
}) {
  const placeholder = searchPlaceholder ?? `Search ${listTitle.toLowerCase()}…`;

  return (
    <div className={styles.page}>
      <LibraryList
        listTitle={listTitle}
        filteredCount={filteredCount}
        totalCount={totalCount}
        searchPlaceholder={placeholder}
        search={search}
        onSearch={onSearch}
        selectedId={selectedId}
        items={items}
        onSelect={onSelect}
        onNew={onNew}
        filters={filters}
      />
      <section className={styles.detail}>
        {emptySelection && mode === "detail" ? (
          <>
            <div className={styles.form}>{children}</div>
            <div className={styles.detailEmpty}>
              <Icon name="Folder" size={24} aria-hidden />
              <div className={styles.detailEmptyMsg}>
                {emptySelectionMessage ?? `Select a ${detailEyebrow} to see details`}
              </div>
            </div>
          </>
        ) : (
          <>
            {mode === "detail" && (
              <div className={styles.detailHead}>
                <div>
                  <div className={styles.eyebrow}>{detailEyebrow}</div>
                  <h1
                    className={
                      detailTitleVariant === "mono" ? `${styles.title} ${styles.titleMono}` : styles.title
                    }
                  >
                    {detailTitle}
                  </h1>
                </div>
                {(onDelete || onEdit) && (
                  <div className={styles.actions}>
                    {onDelete && (
                      <Button
                        size="sm"
                        variant="ghost"
                        type="button"
                        icon={<Icon name="Trash2" />}
                        onClick={onDelete}
                        aria-label="Delete"
                      />
                    )}
                    {onEdit && (
                      <Button
                        size="sm"
                        variant="secondary"
                        type="button"
                        icon={<Icon name="Pencil" />}
                        onClick={onEdit}
                      >
                        Edit
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}
            <div className={mode === "detail" ? styles.body : styles.form}>{children}</div>
          </>
        )}
      </section>
    </div>
  );
}
