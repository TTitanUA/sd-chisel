# sd-chisel

Local prompt writer for ComfyUI. It manages a local library of model families, checkpoints, and LoRAs, analyzes source images with a VL model, supports chat-driven prompt iteration, generates structured positive / negative / LoRA-string output you can paste into your workflow, and provides AI assistants for writing family prompt guides and LoRA metadata. LoRA indexing, Civitai metadata import, and other long-running work run through a background task registry with live UI updates.

See:
- [Technical spec](docs/spec/technical_specifications.md)
- [Roadmap](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md)
- [LMStudio capabilities design](docs/superpowers/specs/2026-04-30-lmstudio-capabilities-design.md)
- [Prompt guide assistant design](docs/superpowers/specs/2026-04-30-prompt-guide-assistant-design.md)

## Status

- Slice 6 (generate-prompt) shipped — full MVP loop is complete: source → analyze → chat → generate → copy structured prompt into ComfyUI. See [roadmap §4 Slice 6](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md).
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
