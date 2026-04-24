# sd-chisel

Local Windows prompt-writer for Stable Diffusion i2i via ComfyUI. Library of LoRAs and models, VL image analysis, chat-driven prompt generation.

See:
- [Technical spec](docs/spec/technical_specifications.md)
- [Roadmap](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md)

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
uv run db-init                     # applies migrations, seeds 10 families
uv run dev-seed                    # insert mock library rows from mvp-ui-mock (optional)

# Frontend
cd ../frontend
pnpm install
```

## Day-to-day

Two terminals:

```bash
# Terminal 1 — backend
cd backend && uv run dev

# Terminal 2 — frontend
cd frontend && pnpm dev
```

Open http://localhost:5173/.

## Backend commands

Run these from `backend/`:

```bash
uv sync --extra dev                # install/update backend dependencies
uv run db-init                     # apply migrations and seed families
uv run dev-seed                    # seed models/loras from mvp-ui-mock (insert-only, idempotent)
uv run dev                         # run API on http://localhost:8000
uv run pytest                      # run backend tests
uv run ruff check                  # lint backend code
```

## Tests

```bash
# Backend
cd backend && uv run pytest

# Frontend
cd frontend && pnpm test
```

## Data

All runtime state — sqlite DB + uploaded images — lives under `./data/` at the repo root. This directory is git-ignored. Delete it to reset everything.
