-- Comfy agents redesign — per-session, user-programmable agents replace
-- the single implicit composer call. Each agent owns its own prompt,
-- model selection, source scope, LoRA toggle, and a list of typed
-- output slots that bind to the workflow's `binding=llm` slots.
--
-- See docs/comfy-agents-redesign.md for the design. Validation
-- (kind allow-list, single-bind rule, workflow-slot compatibility)
-- lives in the service layer; the schema only enforces structural
-- constraints (FKs, the source_scope enum).
--
-- output_slots_json holds the agent's outputs as a JSON list. Each
-- element is `{id, origin, kind, label, description, last_value,
-- bound_to}`. Persisting it as a single JSON column rather than a
-- side-table keeps the read path one query and matches the way
-- workflow slot maps are stored on `comfy_workflows`.

CREATE TABLE comfy_session_agents (
  id                TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  position          INTEGER NOT NULL DEFAULT 0,
  name              TEXT NOT NULL,
  prompt            TEXT NOT NULL DEFAULT '',
  model_name        TEXT,
  model_params_json TEXT,
  source_scope      TEXT NOT NULL DEFAULT 'all'
                     CHECK (source_scope IN ('all', 'selected', 'none')),
  source_ids_json   TEXT,
  loras_enabled     INTEGER NOT NULL DEFAULT 0
                     CHECK (loras_enabled IN (0, 1)),
  output_slots_json TEXT NOT NULL DEFAULT '[]',
  last_run_at       INTEGER,
  created_at        INTEGER NOT NULL,
  updated_at        INTEGER NOT NULL
);

CREATE INDEX idx_comfy_session_agents_session
  ON comfy_session_agents(session_id, position, id);
