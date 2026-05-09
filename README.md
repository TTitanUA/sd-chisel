# sd-chisel

Local prompt writer for ComfyUI. It manages a local library of model families, checkpoints, and LoRAs, analyzes source images with a VL model, supports chat-driven prompt iteration, generates structured positive / negative / LoRA-string output you can paste into your workflow, and provides AI assistants for writing family prompt guides and LoRA metadata. LoRA indexing, Civitai metadata import, and other long-running work run through a background task registry with live UI updates.

See:
- [Technical spec](docs/spec/technical_specifications.md)

## Status

- Slice 6 (generate-prompt) shipped — full MVP loop is complete: source → analyze → chat → generate → copy structured prompt into ComfyUI.
- Post-MVP work in this tree includes LMStudio model capability detection (`vision`, `tool_use`, `reasoning`), library assistants for prompt guides and LoRA metadata, Civitai import helpers, SSE-backed background tasks, and startup sweep/reindex scheduling for LoRAs that were not indexed cleanly.

## Prerequisites

- Python 3.11+
- Node.js 20+ with pnpm (`npm i -g pnpm`)
- `uv` for backend environment and commands
- LMStudio (or a compatible local server) running locally for VL analysis, chat, prompt generation, and library assistants. Configure the server root URL in Settings, e.g. `http://localhost:1234` (not `/v1`).
- LMStudio models with the capabilities you plan to use: `vision` for source-image analysis, prompt/chat-capable text models for session chat and generation, and `tool_use` for the Library assistants.

## First-time setup

```bash
# Backend
cd backend
uv sync --extra dev
uv run db-init                     # apply migrations (DB starts empty — no seed data)

# Frontend
cd ../frontend
pnpm install
```

## Day-to-day

One terminal — the helper runs both servers and merges their stdout, prefixing
each line with `[be]`/`[fe]`. Ctrl+C stops both.

```bash
# Unix / macOS
./scripts/dev.sh

# Windows (PowerShell)
.\scripts\dev.ps1

# Or call the runner directly on any platform
node scripts/dev.mjs
```

Open http://localhost:5173/.

If you'd rather drive the two servers yourself, run `cd backend && uv run dev`
and `cd frontend && pnpm dev` in separate terminals.

## Backend commands

Run these from `backend/`:

```bash
uv sync --extra dev                # install/update backend dependencies
uv run db-init                     # apply migrations (DB starts empty — no seed data)
uv run dev                         # run API on http://localhost:8000
uv run reindex-all                 # rebuild vec_loras for every LoRA (cold-start / model change)
uv run pytest                      # run backend tests
uv run ruff check                  # lint backend code
```

### First LoRA write triggers a model download

The indexer uses `BAAI/bge-m3` (≈2 GB) via `sentence-transformers`. The model is downloaded the **first time** any of these happen:

- `POST` / `PUT` / `DELETE` on `/api/library/loras`
- `uv run reindex-all`

The download lands in the standard HuggingFace cache (`~/.cache/huggingface/`). Subsequent calls are warm. Tests inject a fake embedder via `backend/tests/conftest.py` and never hit the network.

## Tests

```bash
# Backend
cd backend && uv run pytest

# Frontend
cd frontend && pnpm test
```

## Data

All runtime state — sqlite DB + uploaded images — lives under `./data/` at the repo root. This directory is git-ignored. Delete it to reset everything.

## ComfyUI memory between runs

After every Single Run sd-chisel automatically POSTs `/api/free` to ComfyUI with `{"unload_models": true, "free_memory": true}`. ComfyUI's worker thread picks the flags up at the next iteration and runs `unload_all_models()` + `e.reset()` + `gc.collect()` + `soft_empty_cache()`. The unload event in the run trace reports the freed delta — `vram_freed_mb`, `ram_freed_mb`, and the post-unload absolutes — so you can see the operation actually had effect rather than guessing from Task Manager.

**VRAM does come back.** `torch_vram_total` typically drops to a few tens of MB right after the unload — that's the PyTorch CUDA pool being released to the driver.

**RAM is the awkward one.** Even when `gc.collect()` actually deletes every model reference, Python's `pymalloc` allocator on Windows hangs onto its arenas across collections. The ComfyUI process's resident set in Task Manager will look unchanged for runs in a row, then suddenly drop, and you cannot reliably force it to drop sooner from outside the process. This is a Python/Windows quirk, not a sd-chisel or ComfyUI bug.

If RAM growth across runs is a problem for you, you have two options:

### 1 · Recommended: launch ComfyUI with `PYTHONMALLOC=malloc`

This switches Python from `pymalloc` (which retains arenas) to the system allocator, which on Windows is much more willing to return pages to the OS after `gc.collect()`. There is no measurable performance cost for ComfyUI's workload — pymalloc's win is on tiny short-lived allocations, not the large tensors / numpy buffers that dominate here.

```powershell
# Windows (PowerShell) — set per-launch:
$env:PYTHONMALLOC = "malloc"
python main.py
```

```bash
# Linux / macOS (bash):
PYTHONMALLOC=malloc python main.py
```

This is the cheap, transparent fix and should be the first thing you try.

### 2 · Opt-in per session: bounce ComfyUI between runs

Open the session settings drawer for any comfy session and tick **"Restart ComfyUI after each run (aggressive cleanup)"**. With it on, the orchestrator follows the standard `unload_comfy` stage with a `restart_comfy` stage that POSTs `/manager/reboot` to [ComfyUI-Manager](https://github.com/ltdrdata/ComfyUI-Manager). The whole Python process exits and is respawned by Manager's watchdog — guaranteed RAM reclaim because the OS frees the entire process address space.

Turn it on with eyes open:

- **Cold start cost.** The next run waits 30 s+ while ComfyUI re-imports custom nodes and warms up.
- **Disconnects every other client** of that ComfyUI instance — any browser tab on `:8188`, any other tool talking to its API.
- **Requires the ComfyUI-Manager custom node.** Without it, `POST /manager/reboot` 404s and the run trace surfaces a warning. The run itself still succeeded.
- The setting is **per session and defaults to off**. Other sessions on the same ComfyUI instance are unaffected unless you flip their toggle too.

Use it only when sustained RAM growth is actually a problem and `PYTHONMALLOC=malloc` isn't enough.
