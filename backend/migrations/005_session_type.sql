-- Session type (i2i / t2i), chosen at creation time and immutable thereafter.
-- Existing rows backfill to 'i2i' via the column default — every session that
-- existed before this migration was implicitly an image-to-image session.
ALTER TABLE sessions ADD COLUMN session_type TEXT NOT NULL DEFAULT 'i2i'
  CHECK (session_type IN ('i2i','t2i'));
