-- Phase 2: workflow slot mapping. The slot_map binds sd-chisel's
-- logical injection slots (positive_prompt, negative_prompt,
-- main_image) to concrete (node_id, input_name) pairs in the
-- workflow's graph. NULL on a row means "no slot map saved yet";
-- the editor opens with everything unassigned.
--
-- Stored as JSON so the slot list can grow (LoRA-related slots when
-- Q3 is decided) without further migrations. Per-slot value is
-- either null (unassigned) or {"node_id": "...", "input_name": "..."}.
ALTER TABLE comfy_workflows ADD COLUMN slot_map_json TEXT;
