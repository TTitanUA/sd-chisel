-- Add 'comfy_mock' to the session_type CHECK constraint.
--
-- ComfyMock is a UI-exploration session type — peer of i2i / t2i /
-- comfy — that reuses every comfy workflow + slot-map + agent path
-- but emulates LLM calls and workflow generation client-side. See
-- docs/comfy-agents-ui-mock-plan.md.
--
-- SQLite CHECK constraints can't be ALTERed in place; this is the
-- standard table-rebuild recipe (mirrors 013_comfy_session_type).
-- defer_foreign_keys keeps FKs from messages/prompts/etc. valid
-- across the DROP/RENAME pair (rechecked at COMMIT).

PRAGMA defer_foreign_keys = ON;

CREATE TABLE sessions_new (
  id                 TEXT PRIMARY KEY,
  project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name               TEXT,
  session_type       TEXT NOT NULL DEFAULT 'i2i'
                       CHECK (session_type IN ('i2i','t2i','comfy','comfy_mock')),
  model_name         TEXT REFERENCES models(name) ON DELETE SET NULL,
  use_negative       INTEGER NOT NULL DEFAULT 1,
  vl_model_name      TEXT,
  prompt_model_name  TEXT,
  result_image_path  TEXT,
  hidden             INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1)),
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL,
  analyze_settings   TEXT,
  chat_settings      TEXT,
  summarize_settings TEXT,
  generate_settings  TEXT,
  comfy_workflow_id  TEXT REFERENCES comfy_workflows(id) ON DELETE RESTRICT
);

INSERT INTO sessions_new
  SELECT * FROM sessions;

DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;

CREATE INDEX idx_sessions_project ON sessions(project_id, updated_at DESC);
CREATE INDEX idx_sessions_workflow ON sessions(comfy_workflow_id) WHERE comfy_workflow_id IS NOT NULL;
