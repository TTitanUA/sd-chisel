-- Phase 3 prep: comfy sessions persist their composition output as a
-- structured ``payload_json`` keyed by slot label, alongside the legacy
-- ``positive`` / ``negative`` / ``loras_json`` columns that i2i / t2i
-- sessions continue to use. NULL on a row means "legacy GeneratedPrompt
-- shape"; non-NULL means "comfy GeneratedPayload"; the read path checks
-- this column first and falls back to the legacy triple. See spec
-- §3.2 / §4.3 / §10.7.
ALTER TABLE prompts ADD COLUMN payload_json TEXT;
