-- Per-action LLM sampling settings.
--
-- Four user-configurable LLM actions: analyze (VL), chat, summarize, generate.
-- Each action carries an open-ended JSON bundle of sampling parameters
-- (temperature, top_p, top_k, max_tokens, presence_penalty, frequency_penalty,
-- repeat_penalty, seed). The bundle's shape is validated in the application
-- layer; the schema is intentionally flexible so adding a new sampling
-- parameter later is a UI-only change.
--
-- Resolution semantics: at LLM-call time, the per-key merge of the session
-- bundle over the app-default bundle is sent as request payload extras. A
-- NULL session column means "inherit the entire default bundle"; a missing
-- key inside a non-NULL session bundle means "inherit that one key from the
-- default".

ALTER TABLE sessions ADD COLUMN analyze_settings    TEXT;
ALTER TABLE sessions ADD COLUMN chat_settings       TEXT;
ALTER TABLE sessions ADD COLUMN summarize_settings  TEXT;
ALTER TABLE sessions ADD COLUMN generate_settings   TEXT;

ALTER TABLE app_settings ADD COLUMN default_analyze_settings    TEXT;
ALTER TABLE app_settings ADD COLUMN default_chat_settings       TEXT;
ALTER TABLE app_settings ADD COLUMN default_summarize_settings  TEXT;
ALTER TABLE app_settings ADD COLUMN default_generate_settings   TEXT;
