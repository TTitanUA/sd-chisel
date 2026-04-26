import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  buildSourceImageSrc,
  sessionsApi,
  useSessionInvalidation,
  type Session,
} from "@/api/sessions";
import { useLmStudioConfig } from "@/api/settings";
import styles from "./SourceImagePane.module.css";

export function SourceImagePane({ session }: { session: Session }) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const invalidate = useSessionInvalidation();
  const cfg = useLmStudioConfig();

  const upload = useMutation({
    mutationFn: (file: File) => sessionsApi.uploadSource(session.id, file),
    onSuccess: () => {
      setError(null);
      invalidate.session(session.id);
    },
    onError: (err) => setError(String(err)),
  });
  const clear = useMutation({
    mutationFn: () => sessionsApi.clearSource(session.id),
    onSuccess: () => invalidate.session(session.id),
  });
  const analyze = useMutation({
    mutationFn: () => sessionsApi.analyzeSource(session.id),
    onSuccess: () => {
      setError(null);
      invalidate.session(session.id);
    },
    onError: (err) => setError(String(err)),
  });

  const src = buildSourceImageSrc(session);
  const hasImage = !!src;
  const lmConfigured = !!cfg.data?.configured;
  const hasVlModel = !!session.vl_model_name;
  const reason =
    !hasImage ? "Upload a source image first" :
    !hasVlModel ? "No VL model selected — open Session settings" :
    !lmConfigured ? "LMStudio is not configured — open Settings" :
    "Run VL analyze";

  function pickFile(file: File | undefined) {
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setError(`Unsupported type: ${file.type}`);
      return;
    }
    upload.mutate(file);
  }

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Source</span>
        {hasImage && session.vl_summary && <span className={styles.sub}>· VL-analyzed</span>}
        {hasImage && !session.vl_summary && (
          <span className={styles.subTrunc}>· {session.source_image_path}</span>
        )}
        <div className={styles.spacer} />
        <span
          className={styles.subTrunc}
          title={session.vl_model_name ?? "VL model used for this session"}
        >
          VL · {session.vl_model_name ?? "(not set)"}
        </span>
        {hasImage && (
          <Button
            size="sm"
            icon={<Icon name="Sparkles" size={12} />}
            onClick={() => analyze.mutate()}
            disabled={!hasImage || !lmConfigured || !hasVlModel || analyze.isPending}
            title={reason}
          >
            {analyze.isPending ? "Analyzing…" : session.vl_summary ? "Re-analyze" : "Analyze"}
          </Button>
        )}
        {hasImage && (
          <Button
            size="sm"
            icon={<Icon name="Trash2" size={12} />}
            onClick={() => clear.mutate()}
          >
            Clear
          </Button>
        )}
      </div>
      <div className={styles.body}>
        {src ? (
          <div className={styles.stack}>
            <div className={styles.frame}>
              <img src={src} alt="source" />
            </div>
            {analyze.isPending && (
              <div className={styles.summary} data-state="pending">
                <div className={styles.summaryHead}>VL analyzing…</div>
              </div>
            )}
            {!analyze.isPending && session.vl_summary && (
              <div className={styles.summary} data-state="done">
                <div className={styles.summaryHead}>VL summary</div>
                <div className={styles.summaryBody}>{session.vl_summary}</div>
              </div>
            )}
            {error && <div className={styles.error} role="alert">{error}</div>}
          </div>
        ) : (
          <div
            className={styles.drop}
            data-over={over}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              pickFile(e.dataTransfer.files?.[0]);
            }}
          >
            <Icon name="Folder" size={28} />
            <div className={styles.dropTitle}>Drop source image</div>
            <div className={styles.dropSub}>
              PNG/JPEG/WEBP. Stored under <code>data/images/&lt;session&gt;/</code>.
            </div>
            <Button
              size="sm"
              variant="primary"
              onClick={() => inputRef.current?.click()}
              disabled={upload.isPending}
            >
              {upload.isPending ? "Uploading..." : "Choose file"}
            </Button>
            <input
              ref={inputRef}
              hidden
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => pickFile(event.currentTarget.files?.[0] ?? undefined)}
            />
            {error && <div className={styles.error} role="alert">{error}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
