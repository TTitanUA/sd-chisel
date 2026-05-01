import { useEffect, useMemo } from "react";
import { imageDisplayName, type SourceImage } from "@/api/sessions";
import styles from "./MentionPopover.module.css";

export type MentionPopoverProps = {
  open: boolean;
  query: string;
  images: SourceImage[];
  highlightedIndex: number;
  onHighlightChange: (index: number) => void;
  onSelect: (image: SourceImage) => void;
};

export function filterMentionCandidates(
  images: SourceImage[],
  query: string,
): SourceImage[] {
  const sorted = [...images].sort((a, b) => a.image_number - b.image_number);
  const q = query.trim().toLowerCase();
  if (!q) return sorted;
  return sorted.filter((img) => {
    const display = imageDisplayName(img).toLowerCase();
    return (
      display.includes(q) ||
      String(img.image_number).includes(q) ||
      img.original_filename.toLowerCase().includes(q)
    );
  });
}

export function MentionPopover({
  open,
  query,
  images,
  highlightedIndex,
  onHighlightChange,
  onSelect,
}: MentionPopoverProps) {
  const candidates = useMemo(
    () => filterMentionCandidates(images, query),
    [images, query],
  );

  useEffect(() => {
    if (!open) return;
    if (candidates.length === 0) return;
    if (highlightedIndex >= candidates.length) {
      onHighlightChange(0);
    }
  }, [candidates, highlightedIndex, open, onHighlightChange]);

  if (!open) return null;

  return (
    <div className={styles.popover} role="listbox" aria-label="Image mentions">
      {candidates.length === 0 ? (
        <div className={styles.empty}>No matching images.</div>
      ) : (
        candidates.map((img, idx) => {
          const display = imageDisplayName(img);
          const active = idx === highlightedIndex;
          return (
            <button
              key={img.id}
              type="button"
              role="option"
              aria-selected={active}
              data-active={active || undefined}
              className={styles.item}
              onMouseEnter={() => onHighlightChange(idx)}
              onMouseDown={(e) => {
                // mousedown so the textarea doesn't lose focus / move caret
                // before our handler fires.
                e.preventDefault();
                onSelect(img);
              }}
            >
              <span className={styles.itemName}>{display}</span>
              <span className={styles.itemSub}>{img.original_filename}</span>
              {img.is_main && <span className={styles.mainBadge}>main</span>}
            </button>
          );
        })
      )}
    </div>
  );
}

export function getMentionCandidates(
  images: SourceImage[],
  query: string,
): SourceImage[] {
  return filterMentionCandidates(images, query);
}
