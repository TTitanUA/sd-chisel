-- PR-2: groundwork for the Phase 3 generation cycle.
--
-- 1. Adds explicit ComfyUI input/output directory overrides on
--    app_settings. The Phase 1 design assumed sd-chisel could derive
--    both from `comfyui_path/{input,output}` — but ComfyUI lets the
--    user point them anywhere via CLI args, so an override field is
--    needed before Phase 3 can write/read files there. Both default
--    to NULL and the resolver in `app.services.comfy_paths` falls
--    back to `<comfyui_path>/{input,output}` when unset.
--
-- 2. Adds `sessions.comfy_input_cleanup` — what to do with files
--    sd-chisel uploaded into ComfyUI's input dir after a generation
--    finishes. 'keep' (default) leaves them; 'delete' removes them
--    via direct filesystem access (which only works locally — Phase 3
--    soft-degrades to 'keep' when the input dir isn't reachable).
--    Stored on every session so the legacy i2i / t2i flows can ignore
--    it; only comfy / comfy_mock ever read the column.
--
-- 3. Adds `comfy_workflows.output_slot_map_json` — symmetric to
--    `slot_map_json`, but for SaveImage outputs. Stored shape is
--    `{"version": 1, "outputs": [{"label": "...", "node_id": "...",
--    "kind": "image"}]}`. Phase 3 reads this map to know which
--    SaveImage results to copy into
--    `data/images/<sid>/output/<gid>/<label>.<ext>`. NULL = no map
--    saved yet; the editor opens with one auto-derived entry per
--    SaveImage in the graph.

ALTER TABLE app_settings ADD COLUMN comfyui_input_dir  TEXT;
ALTER TABLE app_settings ADD COLUMN comfyui_output_dir TEXT;

-- SQLite can't ALTER a CHECK constraint in place — but we don't need
-- a CHECK here; the API validates the enum and writes the literal
-- string. Default 'keep' makes the column safe for legacy rows.
ALTER TABLE sessions
  ADD COLUMN comfy_input_cleanup TEXT NOT NULL DEFAULT 'keep';

ALTER TABLE comfy_workflows ADD COLUMN output_slot_map_json TEXT;
