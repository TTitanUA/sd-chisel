-- 003_settings.sql — global LMStudio config + cached model list
-- Replaces per-session vl_endpoint / prompt_endpoint with global app_settings
-- and adds session.vl_model_name / session.prompt_model_name pointers.

ALTER TABLE sessions DROP COLUMN vl_endpoint;
ALTER TABLE sessions DROP COLUMN prompt_endpoint;

ALTER TABLE sessions ADD COLUMN vl_model_name TEXT;
ALTER TABLE sessions ADD COLUMN prompt_model_name TEXT;

-- Single-row table (id=1) — easier to reason about than KV pairs.
CREATE TABLE app_settings (
  id                  INTEGER PRIMARY KEY CHECK (id = 1),
  lmstudio_base_url   TEXT,
  lmstudio_api_key    TEXT,
  updated_at          INTEGER NOT NULL
);

INSERT INTO app_settings(id, lmstudio_base_url, lmstudio_api_key, updated_at)
  VALUES (1, NULL, NULL, CAST(strftime('%s','now') AS INTEGER));

-- LMStudio model cache. Populated by `/api/settings/lmstudio/refresh`.
-- role:    which session field this model can be picked into.
--   'vl'     — only vl_model_name
--   'prompt' — only prompt_model_name
--   'both'   — either field (default — user can narrow it later)
-- enabled: hides the model from session dropdowns when false.
CREATE TABLE lm_models (
  name        TEXT PRIMARY KEY,
  role        TEXT NOT NULL DEFAULT 'both' CHECK (role IN ('vl','prompt','both')),
  enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  last_seen   INTEGER NOT NULL
);
