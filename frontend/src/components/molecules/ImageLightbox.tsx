import { useEffect, useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Icon } from "@/components/atoms/Icon";
import {
  buildSourceImageSrc,
  imageDisplayName,
  type SourceImage,
} from "@/api/sessions";
import styles from "./ImageLightbox.module.css";

export function ImageLightbox({
  images,
  startImageId,
  open,
  onOpenChange,
}: {
  images: SourceImage[];
  startImageId: string | null;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const ordered = useMemo(
    () => [...images].sort((a, b) => a.image_number - b.image_number),
    [images],
  );
  const [activeId, setActiveId] = useState<string | null>(startImageId);

  useEffect(() => {
    if (open) setActiveId(startImageId);
  }, [open, startImageId]);

  const activeIndex = activeId
    ? ordered.findIndex((i) => i.id === activeId)
    : -1;
  const safeIndex = activeIndex < 0 ? 0 : activeIndex;
  const active = ordered[safeIndex];

  function step(delta: 1 | -1) {
    if (ordered.length === 0) return;
    const next = (safeIndex + delta + ordered.length) % ordered.length;
    setActiveId(ordered[next]!.id);
  }

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowRight") {
        e.preventDefault();
        step(1);
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        step(-1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, safeIndex, ordered.length]);

  if (!active) return null;
  const src = buildSourceImageSrc(active);
  const display = imageDisplayName(active);
  const showNav = ordered.length > 1;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          aria-describedby={undefined}
        >
          <Dialog.Title className={styles.srOnly}>
            {display}
          </Dialog.Title>

          <div className={styles.counter}>
            {display} · {safeIndex + 1} / {ordered.length}
          </div>

          <Dialog.Close asChild>
            <button
              type="button"
              className={styles.closeBtn}
              aria-label="Close"
            >
              <Icon name="X" size={20} />
            </button>
          </Dialog.Close>

          {showNav && (
            <button
              type="button"
              className={`${styles.navBtn} ${styles.navPrev}`}
              onClick={() => step(-1)}
              aria-label="Previous image"
            >
              <Icon name="ChevronLeft" size={32} />
            </button>
          )}

          <div className={styles.imageWrap}>
            {src ? (
              <img
                src={src}
                alt={active.original_filename}
                className={styles.image}
              />
            ) : (
              <div className={styles.missing}>image missing</div>
            )}
          </div>

          {showNav && (
            <button
              type="button"
              className={`${styles.navBtn} ${styles.navNext}`}
              onClick={() => step(1)}
              aria-label="Next image"
            >
              <Icon name="ChevronRight" size={32} />
            </button>
          )}

          <div className={styles.caption}>
            <span className={styles.captionFile}>
              {active.original_filename}
            </span>
            {active.is_main && <span className={styles.mainBadge}>main</span>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
