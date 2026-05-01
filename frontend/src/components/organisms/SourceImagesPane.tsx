import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  sessionsApi,
  useSessionInvalidation,
  type Session,
} from "@/api/sessions";
import { SourceImageCard } from "@/components/molecules/SourceImageCard";
import styles from "./SourceImagesPane.module.css";

const ACCEPT = ["image/png", "image/jpeg", "image/webp"];

export function SourceImagesPane({ session }: { session: Session }) {
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

  async function uploadFiles(files: FileList | File[] | null | undefined) {
    if (!files) return;
    const list = Array.from(files);
    if (list.length === 0) return;
    for (const file of list) {
      if (!ACCEPT.includes(file.type)) {
        setError(`Unsupported type: ${file.type}`);
        continue;
      }
      try {
        await upload.mutateAsync(file);
      } catch {
        // error is captured by onError; stop the batch on the first failure
        return;
      }
    }
  }

  const sources = session.source_images;

  return (
    <div className={styles.pane} aria-label="Sources pane">
      <div className={styles.head}>
        <span className={styles.title}>Sources</span>
        <span className={styles.sub}>
          {sources.length === 0
            ? "no images"
            : `${sources.length} image${sources.length === 1 ? "" : "s"}`}
        </span>
        <div className={styles.spacer} />
        <span
          className={styles.subTrunc}
          title={session.vl_model_name ?? "VL model used for this session"}
        >
          VL · {session.vl_model_name ?? "(not set)"}
        </span>
        <Button
          size="sm"
          icon={<Icon name="Plus" size={12} />}
          onClick={() => inputRef.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? "Uploading…" : "Add image"}
        </Button>
        <input
          ref={inputRef}
          hidden
          type="file"
          accept={ACCEPT.join(",")}
          multiple
          onChange={(e) => {
            void uploadFiles(e.currentTarget.files);
            e.currentTarget.value = "";
          }}
        />
      </div>

      <div
        className={styles.body}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void uploadFiles(e.dataTransfer.files);
        }}
        data-over={over || undefined}
      >
        {sources.length === 0 ? (
          <div className={styles.empty}>
            <Icon name="Folder" size={28} />
            <div className={styles.emptyTitle}>Drop source images</div>
            <div className={styles.emptySub}>
              PNG/JPEG/WEBP. The first image becomes the <b>main</b>; later
              uploads are references.
            </div>
            <Button
              size="sm"
              variant="primary"
              onClick={() => inputRef.current?.click()}
              disabled={upload.isPending}
            >
              {upload.isPending ? "Uploading…" : "Choose file(s)"}
            </Button>
          </div>
        ) : (
          <div className={styles.list}>
            {sources.map((image) => (
              <SourceImageCard key={image.id} session={session} image={image} />
            ))}
            <div className={styles.dropHint}>
              Drag more images here or use <b>Add image</b>.
            </div>
          </div>
        )}
        {error && <div className={styles.error} role="alert">{error}</div>}
      </div>
    </div>
  );
}
