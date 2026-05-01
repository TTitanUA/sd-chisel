-- 004_hidden_flags.sql — privacy flags
-- Adds a `hidden` flag to every list-displayed entity, plus a `show_hidden`
-- toggle in app_settings. Frontend filters items where hidden=1 unless
-- show_hidden=1 is set.

ALTER TABLE projects  ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1));
ALTER TABLE sessions  ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1));
ALTER TABLE families  ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1));
ALTER TABLE models    ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1));
ALTER TABLE loras     ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1));
ALTER TABLE lm_models ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0,1));

ALTER TABLE app_settings ADD COLUMN show_hidden INTEGER NOT NULL DEFAULT 0 CHECK (show_hidden IN (0,1));
