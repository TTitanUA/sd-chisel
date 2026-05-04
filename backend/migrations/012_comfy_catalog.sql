-- ComfyUI catalog: packs and nodes discovered when the user imports a
-- workflow whose graph references unknown class_types. Tables grow
-- on-demand through the per-node import wizard, not via a bulk sync.
-- See docs/comfy-workflow-plan.md (Phase 1).

-- A pack found under <comfyui_path>/custom_nodes/<dir>/, plus a synthetic
-- row name='ComfyUI' for built-in nodes. Metadata sourced from
-- pyproject.toml; readme_md cached as raw markdown for library detail
-- views and as input to the node import LLM step.
CREATE TABLE comfy_packs (
  name           TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  description    TEXT,
  version        TEXT,
  repo_url       TEXT,
  publisher_id   TEXT,
  -- dir_path is relative to comfyui_path. NULL marks the synthetic ComfyUI built-in pack.
  dir_path       TEXT,
  readme_md      TEXT,
  imported_at    INTEGER NOT NULL
);

-- One row per unique class_type the user has imported. Both the raw
-- INPUT_TYPES schema (ground truth from /api/object_info) and the
-- normalized semantic form with role hints are stored — raw stays
-- untouched on edits, semantic is what slot mapping reads in Phase 2.
--
-- requires_semantic_config = 0 marks "auto-ready" nodes that don't carry
-- mappable slots (Reroute, plumbing, etc.). Phase 1 always writes 1; the
-- column exists so a future detector can flip it without a migration.
CREATE TABLE comfy_nodes (
  class_type                  TEXT PRIMARY KEY,
  pack_name                   TEXT NOT NULL REFERENCES comfy_packs(name) ON DELETE CASCADE,
  display_name                TEXT NOT NULL,
  category                    TEXT,
  inputs_raw_json             TEXT NOT NULL,
  outputs_raw_json            TEXT NOT NULL,
  inputs_semantic_json        TEXT NOT NULL,
  description_md              TEXT NOT NULL,
  requires_semantic_config    INTEGER NOT NULL DEFAULT 1
                                CHECK (requires_semantic_config IN (0,1)),
  imported_at                 INTEGER NOT NULL,
  last_seen_in_object_info_at INTEGER NOT NULL
);

CREATE INDEX idx_comfy_nodes_pack ON comfy_nodes(pack_name);

-- Sparse overlay of user edits. NULL means "no override for this field".
-- On read, comfy_nodes is merged with this table; on re-import, the
-- canonical fields are refreshed without touching overrides.
CREATE TABLE comfy_node_overrides (
  class_type            TEXT PRIMARY KEY REFERENCES comfy_nodes(class_type) ON DELETE CASCADE,
  description_md        TEXT,
  inputs_semantic_json  TEXT,
  category              TEXT,
  updated_at            INTEGER NOT NULL
);

-- API-format workflow JSON uploaded by the user. graph_hash is the
-- canonicalised sha256 used to detect "this is the same JSON" and
-- prompt replace/rename on duplicate uploads.
CREATE TABLE comfy_workflows (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  graph_json  TEXT NOT NULL,
  graph_hash  TEXT NOT NULL,
  created_at  INTEGER NOT NULL
);

CREATE INDEX idx_comfy_workflows_hash ON comfy_workflows(graph_hash);
CREATE INDEX idx_comfy_workflows_created ON comfy_workflows(created_at DESC);

-- Fifth action in the per-action sampling-bundle system, alongside
-- analyze/chat/summarize/generate. Used by Stage 3 of the per-node
-- import wizard. Defaults live here; no per-session override (import is
-- a global, per-class_type operation, not per-session).
ALTER TABLE app_settings ADD COLUMN default_comfy_import_settings TEXT;
