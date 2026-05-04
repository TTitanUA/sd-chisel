-- ComfyUI integration: dedicated settings on the app_settings singleton.
--
-- comfyui_url    — HTTP base URL of the running ComfyUI (e.g. http://127.0.0.1:8188).
-- comfyui_path   — filesystem path to the ComfyUI install; the per-node import
--                  wizard walks <path>/custom_nodes/ to discover packs.
-- comfyui_api_key — optional auth header, mirrors lmstudio_api_key. Most local
--                   ComfyUI deployments have no auth; the field exists so the
--                   same settings flow works against reverse-proxied or cloud
--                   ComfyUI without a follow-up migration.

ALTER TABLE app_settings ADD COLUMN comfyui_url     TEXT;
ALTER TABLE app_settings ADD COLUMN comfyui_path    TEXT;
ALTER TABLE app_settings ADD COLUMN comfyui_api_key TEXT;
