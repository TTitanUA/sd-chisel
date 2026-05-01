-- Multi-source images per session: replace the single `source_image_path`
-- + `vl_summary` columns on `sessions` with a child table that supports
-- many images per session. Exactly one row per session is flagged `is_main`;
-- the rest are reference images. Each row carries its own VL analysis text
-- and the optional refining prompt the user supplied for the last analysis.
--
-- Existing data: clean break — drop the legacy columns and any session that
-- had a source image will need to re-upload. The on-disk cleanup of stale
-- `data/images/<session_id>/source.*` files is intentionally not handled here;
-- the next user-visible upload writes into `sources/`, and the per-session
-- cleanup hook on session delete still wipes the whole session directory.

CREATE TABLE session_source_images (
  id                 TEXT PRIMARY KEY,
  session_id         TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  path               TEXT NOT NULL,
  original_filename  TEXT NOT NULL,
  is_main            INTEGER NOT NULL DEFAULT 0 CHECK (is_main IN (0,1)),
  analysis           TEXT,
  analysis_prompt    TEXT,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);

CREATE INDEX idx_session_source_images_session
  ON session_source_images(session_id, created_at);

CREATE UNIQUE INDEX uniq_session_source_images_main
  ON session_source_images(session_id) WHERE is_main = 1;

-- Drop the legacy columns from `sessions`. SQLite does not support
-- DROP COLUMN before 3.35; recreate the table to stay compatible with older
-- engines and to keep the column order tidy.
CREATE TABLE sessions_new (
  id                 TEXT PRIMARY KEY,
  project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name               TEXT,
  session_type       TEXT NOT NULL DEFAULT 'i2i'
                       CHECK (session_type IN ('i2i','t2i')),
  model_name         TEXT REFERENCES models(name) ON DELETE SET NULL,
  use_negative       INTEGER NOT NULL DEFAULT 1,
  vl_model_name      TEXT,
  prompt_model_name  TEXT,
  result_image_path  TEXT,
  hidden             INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1)),
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);

INSERT INTO sessions_new (
  id, project_id, name, session_type, model_name, use_negative,
  vl_model_name, prompt_model_name, result_image_path, hidden,
  created_at, updated_at
)
SELECT
  id, project_id, name, session_type, model_name, use_negative,
  vl_model_name, prompt_model_name, result_image_path, hidden,
  created_at, updated_at
FROM sessions;

DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;

CREATE INDEX idx_sessions_project ON sessions(project_id, updated_at DESC);
