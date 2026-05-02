-- The chat-summarisation brief that fed this prompt-generation run.
-- Filled when /generate-prompt was invoked with a brief (the new modal
-- flow always supplies one, manual /generate-prompt invocations may
-- still leave it NULL). Stored verbatim so it can be inspected from the
-- prompts history without joining back to the chat log.

ALTER TABLE prompts ADD COLUMN brief TEXT;
