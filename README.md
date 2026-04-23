# sd-chisel

Local Windows prompt-writer for Stable Diffusion i2i via ComfyUI. Library of LoRAs and models, VL image analysis, chat-driven prompt generation.

See:
- [Technical spec](docs/spec/technical_specifications.md)
- [Roadmap](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md)

## Prerequisites

- Python 3.11+
- Node.js 20+ with pnpm (`npm i -g pnpm`)
- `uv` recommended (`pip install uv`); plain pip works too
- LMStudio (or any OpenAI-compatible endpoint) running locally — required in Slice 3+, not for foundation

## First-time setup

```bash
# Backend
cd backend
uv venv
uv pip install -e ".[dev]"
python -m app.cli.init_db          # applies migrations, seeds 10 families

# Frontend
cd ../frontend
pnpm install
```

## Day-to-day

Two terminals:

```bash
# Terminal 1 — backend
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && pnpm dev
```

Open http://localhost:5173/.

## Tests

```bash
# Backend
cd backend && .venv/Scripts/python -m pytest

# Frontend
cd frontend && pnpm test
```

## Data

All runtime state — sqlite DB + uploaded images — lives under `./data/` at the repo root. This directory is git-ignored. Delete it to reset everything.
