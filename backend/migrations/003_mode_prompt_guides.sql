-- Mode-specific prompt guides on families.
-- prompt_guide stays the required base; the two new columns are optional
-- additions for image-to-image and text-to-image modes respectively.
ALTER TABLE families ADD COLUMN prompt_i2i TEXT NOT NULL DEFAULT '';
ALTER TABLE families ADD COLUMN prompt_t2i TEXT NOT NULL DEFAULT '';
