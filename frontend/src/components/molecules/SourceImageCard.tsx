import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  buildSourceImageSrc,
  imageDisplayName,
  sessionsApi,
  useSessionInvalidation,
  type Session,
  type SourceImage,
} from "@/api/sessions";
import { AnalysisDetailModal } from "./AnalysisDetailModal";
import { AnalyzeImageModal } from "./AnalyzeImageModal";
import styles from "./SourceImageCard.module.css";

const PREVIEW_LIMIT = 240;

export function SourceImageCard({
  session,
  image,
  onOpenLightbox,
}: {
  session: Session;
  image: SourceImage;
  onOpenLightbox?: (imageId: string) => void;
}) {
  const invalidate = useSessionInvalidation();
  const [analyzeOpen, setAnalyzeOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);

  const setMain = useMutation({
    mutationFn: () => sessionsApi.setMainSource(session.id, image.id),
    onSuccess: () => invalidate.session(session.id),
  });
  const remove = useMutation({
    mutationFn: () => sessionsApi.deleteSource(session.id, image.id),
    onSuccess: () => invalidate.session(session.id),
  });

  const displayName = imageDisplayName(image);

  function onDeleteClick() {
    if (image.analysis) {
      const ok = window.confirm(
        `Delete ${displayName} (${image.original_filename})? Its analysis will be lost.`,
      );
      if (!ok) return;
    }
    remove.mutate();
  }

  function onToggleMain() {
    if (image.is_main || setMain.isPending) return;
    setMain.mutate();
  }

  const showMain = session.session_type !== "t2i";
  const src = buildSourceImageSrc(image);
  const previewText = image.analysis
    ? image.analysis.length > PREVIEW_LIMIT
      ? image.analysis.slice(0, PREVIEW_LIMIT).trimEnd() + "…"
      : image.analysis
    : null;

  return (
    <>
      <div
        className={styles.card}
        data-main={image.is_main || undefined}
        aria-label={`Source image ${displayName}`}
      >
        <div className={styles.imageWrap}>
          {src ? (
            <button
              type="button"
              className={styles.imageBtn}
              onClick={() => onOpenLightbox?.(image.id)}
              aria-label={`Open ${displayName} fullscreen`}
              title="Click to view fullscreen"
            >
              <img src={src} alt={image.original_filename} />
            </button>
          ) : (
            <div className={styles.imageMissing}>missing</div>
          )}
          {showMain && (
            <button
              type="button"
              className={styles.starBtn}
              data-active={image.is_main || undefined}
              onClick={onToggleMain}
              disabled={image.is_main || setMain.isPending}
              aria-label={image.is_main ? "Main image" : "Set as main"}
              title={image.is_main ? "Main image" : "Set as main"}
            >
              <Icon name="Star" size={14} />
            </button>
          )}
          {showMain && image.is_main && (
            <span className={styles.mainBadge}>main</span>
          )}
        </div>

        <div className={styles.center}>
          <div className={styles.title} title={displayName}>
            {displayName}
          </div>
          <div className={styles.filename} title={image.original_filename}>
            {image.original_filename}
          </div>
          <div className={styles.summaryLabel}>VL summary</div>
          {previewText ? (
            <button
              type="button"
              className={styles.summaryBtn}
              onClick={() => setDetailOpen(true)}
              aria-label="Show full analysis"
              title="Show full analysis"
            >
              {previewText}
            </button>
          ) : (
            <div className={styles.summaryEmpty}>Not analyzed yet</div>
          )}
        </div>

        <div className={styles.actions}>
          <Button
            size="sm"
            variant="primary"
            icon={<Icon name="Sparkles" size={12} />}
            onClick={() => setAnalyzeOpen(true)}
          >
            {image.analysis ? "Re-analyze" : "Analyze"}
          </Button>
          <Button
            size="sm"
            icon={<Icon name="Trash2" size={12} />}
            onClick={onDeleteClick}
            disabled={remove.isPending}
          >
            {remove.isPending ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </div>

      <AnalyzeImageModal
        session={session}
        image={image}
        open={analyzeOpen}
        onOpenChange={setAnalyzeOpen}
      />
      <AnalysisDetailModal
        image={image}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />
    </>
  );
}
