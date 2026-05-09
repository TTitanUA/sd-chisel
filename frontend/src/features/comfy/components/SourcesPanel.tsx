/** Source images panel — slot management on top, raw image grid
 *  below.
 *
 *  The slot table is the source of truth for "which image plays
 *  which role" — agents reference slot ids, slots map to images.
 *  The raw image grid below is just the dumb library of available
 *  pixels.
 *
 *  Interaction model:
 *
 *  - **Click an image** opens a lightbox with the full-size
 *    preview. The legacy "click to set main" behaviour is gone —
 *    the `main` purpose now lives on slots, not on individual
 *    images.
 *  - **Drag an image onto a slot row** binds the image to that
 *    slot. The slot row highlights while a drag is hovering it.
 *
 *  See docs/comfy-agents-ui-mock-plan.md.
 */
import { useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { sessionsApi, sessionKeys, type SourceImage } from "@/api/sessions";
import { useComfy } from "../state/useComfy";
import {
  SOURCE_PURPOSES,
  SOURCE_PURPOSE_LABEL,
  nextImageKey,
  nextPurpose,
  type SourcePurpose,
  type SourceSlot,
} from "../state/source-slots";
import { Lightbox } from "./Lightbox";
import styles from "./SourcesPanel.module.css";

/** Drag MIME-type for image-id payloads. Picked specifically so the
 *  browser doesn't interpret a drop somewhere else (e.g. a textbox)
 *  as a generic text paste. */
const DND_MIME = "application/x-comfymock-source-image";

export function SourcesPanel() {
  const {
    session,
    sourceSlots,
    addSourceSlot,
    patchSourceSlot,
    removeSourceSlot,
  } = useComfy();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [openSlotId, setOpenSlotId] = useState<string | null>(null);
  const [dragImageId, setDragImageId] = useState<string | null>(null);
  const [dragOverSlotId, setDragOverSlotId] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<SourceImage | null>(null);
  const client = useQueryClient();

  const refresh = () => {
    void client.invalidateQueries({
      queryKey: sessionKeys.session(session.id),
    });
  };

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await sessionsApi.uploadSource(session.id, file);
      }
      refresh();
    } catch (err) {
      console.error("[ComfyMock] source upload failed", err);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const handleDelete = async (image: SourceImage) => {
    if (!confirm(`Delete ${image.original_filename}?`)) return;
    await sessionsApi.deleteSource(session.id, image.id);
    refresh();
  };

  // Granular CRUD — each call is one server round-trip with optimistic
  // refresh via TanStack Query invalidation in the hooks.
  function patchSlot(id: string, patch: Partial<SourceSlot>) {
    void patchSourceSlot(id, {
      // Drop fields the user didn't touch — Pydantic distinguishes
      // "absent" (leave alone) from "explicit null" (clear).
      ...(patch.key !== undefined && { key: patch.key }),
      ...(patch.purpose !== undefined && { purpose: patch.purpose }),
      ...("description" in patch && { description: patch.description ?? null }),
      ...("source_image_id" in patch && {
        source_image_id: patch.source_image_id ?? null,
      }),
    });
  }
  function deleteSlot(id: string) {
    if (openSlotId === id) setOpenSlotId(null);
    void removeSourceSlot(id);
  }
  async function addSlot() {
    const slot = await addSourceSlot({
      key: nextImageKey(sourceSlots),
      purpose: nextPurpose(sourceSlots),
    });
    if (slot) setOpenSlotId(slot.id);
  }

  // Drag-and-drop wiring. We consider a drag valid only when the
  // dataTransfer carries our private MIME — that way the browser's
  // default "drop a file from disk to upload" path is left alone.
  function onImageDragStart(e: React.DragEvent, image: SourceImage) {
    e.dataTransfer.setData(DND_MIME, image.id);
    e.dataTransfer.effectAllowed = "link";
    setDragImageId(image.id);
  }
  function onImageDragEnd() {
    setDragImageId(null);
    setDragOverSlotId(null);
  }
  function onSlotDragOver(e: React.DragEvent, slotId: string) {
    if (!Array.from(e.dataTransfer.types).includes(DND_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "link";
    if (dragOverSlotId !== slotId) setDragOverSlotId(slotId);
  }
  function onSlotDragLeave(slotId: string) {
    if (dragOverSlotId === slotId) setDragOverSlotId(null);
  }
  function onSlotDrop(e: React.DragEvent, slot: SourceSlot) {
    const id = e.dataTransfer.getData(DND_MIME);
    if (!id) return;
    e.preventDefault();
    setDragOverSlotId(null);
    setDragImageId(null);
    patchSlot(slot.id, { source_image_id: id });
  }

  const boundImageIds = useMemo(() => {
    const set = new Set<string>();
    for (const s of sourceSlots) {
      if (s.source_image_id) set.add(s.source_image_id);
    }
    return set;
  }, [sourceSlots]);

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <span className={styles.title}>
          Sources ({session.source_images.length} img / {sourceSlots.length} slot)
        </span>
        <button
          type="button"
          className={styles.upload}
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          title="Upload one or more files"
        >
          {uploading ? "Uploading…" : "+ upload"}
        </button>
        <button type="button" className={styles.upload} onClick={addSlot}>
          + slot
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="image/*"
          multiple
          style={{ display: "none" }}
          onChange={(e) => handleUpload(e.target.files)}
        />
      </div>

      <div className={styles.body}>
        <section className={styles.section}>
          <div className={styles.sectionHead}>
            SLOTS
            {dragImageId && (
              <span className={styles.dragHint}>drop on a slot to bind</span>
            )}
          </div>
          {sourceSlots.length === 0 && (
            <div className={styles.empty}>
              No source slots. Click <strong>+ slot</strong> above to declare
              a role like "Main" or "Scene reference" — agents bind to slots,
              not to images directly.
            </div>
          )}
          <div className={styles.slotList}>
            {sourceSlots.map((slot) => {
              const image =
                session.source_images.find(
                  (i) => i.id === slot.source_image_id,
                ) ?? null;
              const expanded = openSlotId === slot.id;
              const isDragOver = dragOverSlotId === slot.id;
              return (
                <div
                  key={slot.id}
                  className={`${styles.slot} ${isDragOver ? styles.slotDropOver : ""}`}
                  onDragOver={(e) => onSlotDragOver(e, slot.id)}
                  onDragLeave={() => onSlotDragLeave(slot.id)}
                  onDrop={(e) => onSlotDrop(e, slot)}
                >
                  <button
                    type="button"
                    className={styles.slotHead}
                    data-purpose={slot.purpose}
                    onClick={() =>
                      setOpenSlotId(expanded ? null : slot.id)
                    }
                  >
                    <span className={styles.slotPurpose}>
                      {SOURCE_PURPOSE_LABEL[slot.purpose]}
                    </span>
                    <span className={styles.slotKey}>{slot.key}</span>
                    <span className={styles.slotBound}>
                      {image ? (
                        <>
                          <img
                            className={styles.slotThumb}
                            src={image.url}
                            alt={image.original_filename}
                          />
                          <span className={styles.slotImgName}>
                            {image.original_filename}
                          </span>
                        </>
                      ) : (
                        <span className={styles.slotEmpty}>(unbound)</span>
                      )}
                    </span>
                    <span className={styles.slotChev}>
                      {expanded ? "▾" : "▸"}
                    </span>
                  </button>
                  {expanded && (
                    <SlotEditor
                      slot={slot}
                      images={session.source_images}
                      otherKeys={
                        new Set(
                          sourceSlots.filter((s) => s.id !== slot.id).map((s) => s.key),
                        )
                      }
                      onPatch={(patch) => patchSlot(slot.id, patch)}
                      onDelete={() => deleteSlot(slot.id)}
                      onPreview={(img) => setLightbox(img)}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section className={styles.section}>
          <div className={styles.sectionHead}>IMAGES</div>
          {session.source_images.length === 0 && (
            <div className={styles.empty}>
              No source images. Drag a file or click upload.
            </div>
          )}
          <div className={styles.grid}>
            {session.source_images.map((image) => {
              const isBound = boundImageIds.has(image.id);
              const isDragging = dragImageId === image.id;
              return (
                <div
                  key={image.id}
                  className={`${styles.item} ${isBound ? styles.bound : ""} ${
                    isDragging ? styles.dragging : ""
                  }`}
                >
                  <button
                    type="button"
                    className={styles.thumb}
                    onClick={() => setLightbox(image)}
                    draggable
                    onDragStart={(e) => onImageDragStart(e, image)}
                    onDragEnd={onImageDragEnd}
                    title="Click to preview · drag onto a slot to bind"
                  >
                    <img src={image.url} alt={image.original_filename} />
                    {!isBound && (
                      <span className={styles.unboundBadge}>unbound</span>
                    )}
                  </button>
                  <div className={styles.itemMeta}>
                    <span className={styles.filename}>
                      {image.original_filename}
                    </span>
                    <button
                      type="button"
                      className={styles.deleteBtn}
                      onClick={() => handleDelete(image)}
                    >
                      ×
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {lightbox && (
        <Lightbox
          src={lightbox.url}
          caption={lightbox.original_filename}
          onClose={() => setLightbox(null)}
        />
      )}
    </div>
  );
}

// --- per-slot editor ----------------------------------------------------

function SlotEditor({
  slot,
  images,
  otherKeys,
  onPatch,
  onDelete,
  onPreview,
}: {
  slot: SourceSlot;
  images: SourceImage[];
  otherKeys: Set<string>;
  onPatch: (patch: Partial<SourceSlot>) => void;
  onDelete: () => void;
  onPreview: (image: SourceImage) => void;
}) {
  const keyInvalid = !slot.key.trim() || otherKeys.has(slot.key);
  const boundImage =
    images.find((i) => i.id === slot.source_image_id) ?? null;
  return (
    <div className={styles.slotForm}>
      <label className={styles.field}>
        <span>key</span>
        <input
          className={styles.input}
          value={slot.key}
          aria-invalid={keyInvalid || undefined}
          onChange={(e) => onPatch({ key: e.currentTarget.value })}
        />
      </label>
      {keyInvalid && (
        <div className={styles.errorRow}>
          {!slot.key.trim()
            ? "Key is required."
            : `Key "${slot.key}" is already used by another slot.`}
        </div>
      )}

      <label className={styles.field}>
        <span>purpose</span>
        <select
          className={styles.input}
          value={slot.purpose}
          onChange={(e) =>
            onPatch({ purpose: e.currentTarget.value as SourcePurpose })
          }
        >
          {SOURCE_PURPOSES.map((p) => (
            <option key={p} value={p}>
              {SOURCE_PURPOSE_LABEL[p]}
            </option>
          ))}
        </select>
      </label>

      <label className={styles.field}>
        <span>image</span>
        <div className={styles.imageRow}>
          <select
            className={styles.input}
            value={slot.source_image_id ?? ""}
            onChange={(e) =>
              onPatch({ source_image_id: e.currentTarget.value || null })
            }
          >
            <option value="">(unbound)</option>
            {images.map((img) => (
              <option key={img.id} value={img.id}>
                {img.original_filename}
              </option>
            ))}
          </select>
          {boundImage && (
            <button
              type="button"
              className={styles.previewBtn}
              onClick={() => onPreview(boundImage)}
              title="Preview"
            >
              <img src={boundImage.url} alt="" />
            </button>
          )}
        </div>
      </label>

      <label className={styles.field}>
        <span>description</span>
        <textarea
          className={styles.input}
          rows={2}
          value={slot.description ?? ""}
          onChange={(e) =>
            onPatch({ description: e.currentTarget.value || null })
          }
          placeholder="Optional note — what does this image represent?"
        />
      </label>

      <div className={styles.formActions}>
        <button type="button" className={styles.delete} onClick={onDelete}>
          Remove slot
        </button>
      </div>
    </div>
  );
}
