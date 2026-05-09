-- Per-session opt-in: send a ComfyUI process restart after every Single Run.
--
-- Why this exists. The default unload_comfy stage POSTs /api/free which
-- triggers ComfyUI's worker to call unload_all_models() + e.reset() +
-- gc.collect(). VRAM does come back (PyTorch's CUDA pool is released),
-- but Python's pymalloc on Windows holds onto allocated arenas across
-- gc.collect() — so the ComfyUI Python process's RSS in Task Manager
-- stays inflated even after the model is logically dropped. Re-running
-- accumulates this until the process is restarted.
--
-- Two mitigations are documented in README.md: (1) launch ComfyUI with
-- PYTHONMALLOC=malloc — uses the system allocator instead of pymalloc,
-- which usually returns memory to the OS; (2) this opt-in column —
-- when set, the orchestrator follows unload_comfy with a
-- POST /manager/reboot to ComfyUI-Manager so the whole process bounces.
-- Default 0 (off) because the reboot adds a 30s+ cold start to the next
-- run and disconnects every other client of that ComfyUI instance.

ALTER TABLE sessions
  ADD COLUMN comfy_restart_after_run INTEGER NOT NULL DEFAULT 0
    CHECK (comfy_restart_after_run IN (0, 1));
