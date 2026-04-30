# sd-chisel

Local Windows prompt-writer for Stable Diffusion i2i via ComfyUI. Library of LoRAs and models, VL image analysis, chat-driven prompt generation.

See:
- [Technical spec](docs/spec/technical_specifications.md)
- [Roadmap](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md)

## Status

- Slice 6 (generate-prompt) shipped — full MVP loop is complete: source → analyze → chat → generate → copy structured prompt into ComfyUI. See [roadmap §4 Slice 6](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md).

## Prerequisites

- Python 3.11+
- Node.js 20+ with pnpm (`npm i -g pnpm`)
- `uv` for backend environment and commands
- LMStudio (or any OpenAI-compatible endpoint) running locally — required in Slice 3+, not for foundation

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
