-- Phase 3 — Single Run job persistence.
--
-- One row per Single Run on `comfy_jobs`, plus N rows per job on
-- `comfy_job_outputs` (one per file the SaveImage step produced).
-- The schema is the durable record of every run; the live SSE
-- pipeline event stream is rebuilt from these rows + an in-memory
-- channel by the orchestrator.
--
-- Design notes:
--
-- * `prompt_id` is the `prompt_id` ComfyUI returned from
--   `POST /api/prompt`. Lives on the row so we can reconcile the WS
--   stream and the history fetch even if the orchestrator
--   reconnects mid-run. NULL while the run is still in the
--   pre-queue stages (validate / snapshot / agents / unload_lm /
--   upload_inputs / patch).
-- * `generation_id` is the `YYYYMMDD-HHMMSS-rrrrrr` stamp from
--   PR-2 prep (see app.utils.generation_id). It's also the on-disk
--   folder name for outputs.
-- * `payload_json` is the merged payload at run time — slot label
--   → value, with agent `last_value`s + frozen + image bindings.
--   This is what got patched into the graph (sans the override
--   layer applied last in the patcher).
-- * `slot_map_snapshot_json` and `agents_snapshot_json` freeze the
--   state of the workflow's slot map and the session's agents at
--   the moment of the run. Together with `payload_json` they make
--   the run reproducible-of-record (not replayable — see plan).
-- * `status` follows the orchestrator's lifecycle:
--     queued → running → success | error | cancelled.
--   `queued` is reserved for batch-level queuing (future Batch Run
--   phase); v1 Single Run jumps straight to `running` after the
--   snapshot stage.
-- * `comfy_job_outputs.slot_label` is nullable: SaveImage results
--   not in the workflow's output map are still recorded with
--   `slot_label=NULL` so the user can see "untracked outputs"
--   warnings on the run row.
-- * `is_primary` marks the first output of the first SaveImage-class
--   node in the output map. The gallery thumbnail reads it.

CREATE TABLE comfy_jobs (
  id                       TEXT PRIMARY KEY,
  session_id               TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  workflow_id              TEXT NOT NULL,
  prompt_id                TEXT,
  generation_id            TEXT NOT NULL,
  payload_json             TEXT NOT NULL DEFAULT '{}',
  slot_map_snapshot_json   TEXT NOT NULL,
  agents_snapshot_json     TEXT NOT NULL DEFAULT '[]',
  status                   TEXT NOT NULL DEFAULT 'running'
                            CHECK (status IN ('queued', 'running', 'success',
                                              'error', 'cancelled')),
  error_message            TEXT,
  started_at               INTEGER NOT NULL,
  finished_at              INTEGER
);

CREATE INDEX idx_comfy_jobs_session
  ON comfy_jobs(session_id, started_at DESC);

CREATE INDEX idx_comfy_jobs_prompt_id
  ON comfy_jobs(prompt_id) WHERE prompt_id IS NOT NULL;

CREATE TABLE comfy_job_outputs (
  id            TEXT PRIMARY KEY,
  job_id        TEXT NOT NULL REFERENCES comfy_jobs(id) ON DELETE CASCADE,
  slot_label    TEXT,
  node_id       TEXT NOT NULL,
  output_index  INTEGER NOT NULL DEFAULT 0,
  path          TEXT NOT NULL,
  is_primary    INTEGER NOT NULL DEFAULT 0
                 CHECK (is_primary IN (0, 1)),
  created_at    INTEGER NOT NULL
);

CREATE INDEX idx_comfy_job_outputs_job
  ON comfy_job_outputs(job_id, output_index);
