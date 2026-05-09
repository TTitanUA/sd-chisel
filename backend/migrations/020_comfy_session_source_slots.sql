-- SourceSlot graduation — promote the per-session "named source slot"
-- table from localStorage to the backend.
--
-- Until now the SourceSlot indirection (slot id → source_image_id)
-- lived browser-side under `comfymock:source-slots:<session_id>` in
-- localStorage. The workflow slot map's `metadata.source_slot_id`
-- and the agents' `model_params.__input_slots[].source.source_slot_id`
-- both stored those ids on the server, so when localStorage was lost
-- (different browser, private mode, manual clear, or the "delete the
-- last slot" branch in saveSourceSlots) the server-side references
-- pointed at nothing and the user saw "(unbound — Generate will fail)".
--
-- The new table mirrors the localStorage shape exactly:
--   id, position (display order), key (display name, unique within
--   session), purpose (main / ref_in_scene / ref_text_only),
--   description (free text fed to the agent's VL prompt), and
--   source_image_id (FK into session_source_images, nullable so
--   "unbound" stays representable).
--
-- The frontend keeps writing the existing ids (we accept client-
-- provided ids on POST so the migration shim can preserve every
-- workflow / agent reference that already exists in the DB).
-- `source_image_id` uses ON DELETE SET NULL so dropping an image
-- doesn't cascade-delete the slot — the slot stays as "unbound".
-- Session deletion still cascades the slot rows.

CREATE TABLE comfy_session_source_slots (
  id                TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  position          INTEGER NOT NULL DEFAULT 0,
  key               TEXT NOT NULL,
  purpose           TEXT NOT NULL DEFAULT 'main'
                     CHECK (purpose IN ('main', 'ref_in_scene', 'ref_text_only')),
  description       TEXT,
  source_image_id   TEXT REFERENCES session_source_images(id) ON DELETE SET NULL,
  created_at        INTEGER NOT NULL,
  updated_at        INTEGER NOT NULL,
  UNIQUE (session_id, key)
);

CREATE INDEX idx_comfy_session_source_slots_session
  ON comfy_session_source_slots(session_id, position, id);
