-- Per-session, never-reused ordinal for source images. Used as the
-- canonical identifier in chat / prompt LLM context (`Image_3`) and as
-- the user-facing label that replaces `original_filename` in the UI.
--
-- Numbers are 1-based per session. Once assigned, an image's number is
-- never reused — even if the row is deleted. New uploads get
-- MAX(image_number) + 1, so deletions leave gaps. This guarantees that
-- LLM references like `@Image_3` stay unambiguous across delete + re-upload.

ALTER TABLE session_source_images
  ADD COLUMN image_number INTEGER NOT NULL DEFAULT 0;

-- Backfill existing rows: for each session, assign 1..N in upload order.
WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (
    PARTITION BY session_id ORDER BY created_at ASC, rowid ASC
  ) AS n
  FROM session_source_images
)
UPDATE session_source_images
   SET image_number = (
     SELECT n FROM ordered WHERE ordered.id = session_source_images.id
   );

CREATE UNIQUE INDEX uniq_session_source_images_number
  ON session_source_images(session_id, image_number);
