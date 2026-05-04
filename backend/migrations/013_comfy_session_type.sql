-- Adds 'comfy' as a session_type and a comfy_workflow_id FK that binds
-- a comfy session to its workflow. The existing CHECK constraint
-- restricting session_type to ('i2i','t2i') has to be replaced, which
-- requires a full table rebuild per SQLite's table-mutation recipe.
-- defer_foreign_keys keeps FKs from messages/prompts/etc. valid across
-- the DROP/RENAME pair (rechecked at COMMIT).

PRAGMA defer_foreign_keys = ON;

CREATE TABLE sessions_new (
  id                 TEXT PRIMARY KEY,
  project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name               TEXT,
  session_type       TEXT NOT NULL DEFAULT 'i2i'
                       CHECK (session_type IN ('i2i','t2i','comfy')),
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
  (id, project_id, name, session_type, model_name, use_negative,
   vl_model_name, prompt_model_name, result_image_path, hidden,
   created_at, updated_at,
   analyze_settings, chat_settings, summarize_settings, generate_settings,
   comfy_workflow_id)
SELECT
  id, project_id, name, session_type, model_name, use_negative,
  vl_model_name, prompt_model_name, result_image_path, hidden,
  created_at, updated_at,
  analyze_settings, chat_settings, summarize_settings, generate_settings,
  NULL
FROM sessions;

DROP TABLE sessions;
ALTER TABLE sessions_new RENAME TO sessions;

CREATE INDEX idx_sessions_project ON sessions(project_id, updated_at DESC);
CREATE INDEX idx_sessions_workflow ON sessions(comfy_workflow_id) WHERE comfy_workflow_id IS NOT NULL;
