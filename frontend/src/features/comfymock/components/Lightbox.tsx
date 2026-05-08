/** Modal image preview. Click the backdrop or press Escape to
 *  close. Used by the SourcesPanel to inspect uploaded images at
 *  full resolution; reusable elsewhere if other panels grow a
 *  thumbnail. See docs/comfy-agents-ui-mock-plan.md.
 */
import { useEffect } from "react";
import styles from "./Lightbox.module.css";

export function Lightbox({
  src,
  caption,
  onClose,
}: {
  src: string;
  caption?: string;
  onClose: () => void;
}) {
  // Close on Escape — the click-on-backdrop path is wired below in
  // the JSX. We intentionally don't prevent scroll-lock; the panel's
  // overflow:auto inside the variant shell keeps things contained.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className={styles.backdrop}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={caption ?? "Image preview"}
    >
      <button
        type="button"
        className={styles.close}
        onClick={onClose}
        aria-label="Close preview"
      >
        ×
      </button>
      <img
        className={styles.img}
        src={src}
        alt={caption ?? ""}
        onClick={(e) => e.stopPropagation()}
      />
      {caption && (
        <div className={styles.caption} onClick={(e) => e.stopPropagation()}>
          {caption}
        </div>
      )}
    </div>
  );
}
