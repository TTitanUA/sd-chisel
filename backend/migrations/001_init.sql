-- 001_init.sql — initial schema for sd-chisel
-- Source of truth: docs/spec/technical_specifications.md §3

-- Library: families / models / loras
CREATE TABLE families (
  id            TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  prompt_guide  TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE models (
  name          TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  family_id     TEXT NOT NULL REFERENCES families(id) ON DELETE RESTRICT,
  description   TEXT,
  author        TEXT,
  version       TEXT,
  source_url    TEXT,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE loras (
  name                TEXT PRIMARY KEY,
  display_name        TEXT NOT NULL,
  description         TEXT NOT NULL,
  tags                TEXT NOT NULL DEFAULT '[]',
  trigger_words       TEXT NOT NULL DEFAULT '[]',
  recommended_weight  REAL,
  author              TEXT,
  version             TEXT,
  source_url          TEXT,
  family_id           TEXT NOT NULL REFERENCES families(id) ON DELETE RESTRICT,
  created_at          INTEGER NOT NULL,
  updated_at          INTEGER NOT NULL
);

-- sqlite-vec virtual table. Dimension 1024 = BAAI/bge-m3 (spec §7).
CREATE VIRTUAL TABLE vec_loras USING vec0(embedding FLOAT[1024]);

CREATE TABLE lora_vec_map (
  lora_name  TEXT PRIMARY KEY REFERENCES loras(name) ON DELETE CASCADE,
  rowid      INTEGER NOT NULL UNIQUE
);

-- Projects / sessions / chat / prompt history
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE sessions (
  id                 TEXT PRIMARY KEY,
  project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name               TEXT,
  model_name         TEXT REFERENCES models(name) ON DELETE SET NULL,
  use_negative       INTEGER NOT NULL DEFAULT 1,
  vl_model_name      TEXT,
  prompt_model_name  TEXT,
  vl_summary         TEXT,
  source_image_path  TEXT,
  result_image_path  TEXT,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);
CREATE INDEX idx_sessions_project ON sessions(project_id, updated_at DESC);

CREATE TABLE session_pinned_loras (
  session_id       TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  lora_name        TEXT NOT NULL REFERENCES loras(name)  ON DELETE CASCADE,
  weight_override  REAL,
  PRIMARY KEY (session_id, lora_name)
);

CREATE TABLE messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content     TEXT NOT NULL,
  created_at  INTEGER NOT NULL
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

CREATE TABLE prompts (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id            TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  positive              TEXT NOT NULL,
  negative              TEXT,
  loras_json            TEXT NOT NULL,
  intents_json          TEXT,
  retrieved_loras_json  TEXT,
  created_at            INTEGER NOT NULL
);
CREATE INDEX idx_prompts_session ON prompts(session_id, created_at);

-- Global LMStudio settings. Single-row table (id=1) — easier to reason about
-- than KV pairs.
CREATE TABLE app_settings (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  lmstudio_url     TEXT,
  lmstudio_api_key TEXT,
  updated_at       INTEGER NOT NULL
);

INSERT INTO app_settings(id, lmstudio_url, lmstudio_api_key, updated_at)
  VALUES (1, NULL, NULL, CAST(strftime('%s','now') AS INTEGER));

-- LMStudio model cache. Populated by `/api/settings/lmstudio/refresh`.
-- Capabilities are auto-detected from the model via LMStudio API.
-- enabled: hides the model from session dropdowns when false.
CREATE TABLE lm_models (
  name      TEXT PRIMARY KEY,
  enabled   INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  last_seen INTEGER NOT NULL,
  vision    INTEGER NOT NULL DEFAULT 0 CHECK (vision IN (0,1)),
  tool_use  INTEGER NOT NULL DEFAULT 0 CHECK (tool_use IN (0,1)),
  reasoning INTEGER NOT NULL DEFAULT 0 CHECK (reasoning IN (0,1))
);
