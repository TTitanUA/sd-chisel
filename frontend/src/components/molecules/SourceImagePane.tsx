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
import styles from "./SourceImagePane.module.css";

export function SourceImagePane({ session }: { session: Session }) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const invalidate = useSessionInvalidation();

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

  const src = buildSourceImageSrc(session);

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
        {src && <span className={styles.sub}>· {session.source_image_path}</span>}
        <div className={styles.spacer} />
        {src && (
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
          <div className={styles.frame}>
            <img src={src} alt="source" />
          </div>
        ) : (
          <div
            className={styles.drop}
            data-over={over}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
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
              PNG/JPEG/WEBP. Stored under <code>data/images/&lt;session&gt;/</code> and served at
              <code> /media/images/…</code>.
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
            {error && <div className={styles.error}>{error}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
