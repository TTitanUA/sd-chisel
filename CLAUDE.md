# CLAUDE.md — sd-chisel

## Documentation language

All documentation in this repo is **English-only**. That includes
`README.md`, every file under `docs/`, in-repo design notes, and any new
docs you add. If you find a doc in another language, translate it as part
of the change you're making — don't leave a mixed-language tree. User
chat in other languages is fine, but anything written to a doc file goes
in English.

## Maintain the technical specification

The single source of truth for *how the app works* is
[`docs/spec/technical_specifications.md`](docs/spec/technical_specifications.md).
It is a **living document**, not historical. After completing any task that
changes user-visible behavior, data model, API surface, or internal flows,
update the spec in the same change.

### When to update

Update the spec whenever any of these are touched:

- Database schema (new migrations in `backend/migrations/`, new/renamed
  columns, new tables, changed FK semantics).
- API endpoints (new/removed routes, changed request/response shape, new SSE
  streams).
- LLM flows (analyze-source, chat, generate-prompt, assistants) — inputs,
  prompts, output schema, retrieval/composition logic.
- Background tasks / task runner behavior.
- LMStudio integration (capabilities, settings, model selection).
- Frontend routes, screens, or major component reorganization.
- Dependencies (added/removed runtime deps in `pyproject.toml` or
  `package.json`).
- Repo structure (new top-level dirs, moved modules).
- MVP scope changes — what shipped vs. what's deferred.

If the change is purely internal refactor with no behavioral or
architectural impact, the spec usually stays the same — but skim the
relevant section to be sure.

### How to update

- The spec describes **behavior**, not code. No SQL DDL, no code blocks, no
  function signatures. Prose and structured lists only. Endpoint paths and
  table/column names are fine; their definitions are not.
- Update the relevant section in place rather than appending. If a feature
  moves from "out of scope" to shipped, move it across §9 too.
- If the change introduces a new section, place it in the existing
  numbering scheme.
- Mention the spec edit explicitly in the task summary at the end of the
  turn — so the user can see it landed.

### Don't

- Don't let the spec drift. If you notice it's out of date while doing an
  unrelated task, flag it (or fix it as part of that task if cheap) — don't
  silently leave the gap.
- Don't paste raw schema snippets, API handler code, or component code into
  the spec. Describe what they do.
- Don't add a changelog/diary section. The spec describes the *current*
  state. Git history is the changelog.
