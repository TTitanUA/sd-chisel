# MVP roadmap — foundation-first + vertical slices

**Status:** design approved 2026-04-23. Supplements `docs/spec/technical_specifications.md` — spec фиксирует *что* строим, этот документ — *в каком порядке* и *с какими границами фаз*.

---

## 1. Подход

**Foundation-first → 6 vertical slices.**

Сначала один раз собираем фундамент (работающий скелет бэка и фронта + БД-схема + сиды справочников + дизайн-токены + тулинг). После этого MVP режется на тонкие end-to-end срезы: каждый срез = бэк + фронт + integration, после среза приложение остаётся работоспособным в рамках уже реализованного.

**Почему не vertical-first:** без БД со всеми таблицами и без сидов families любой первый срез либо вырождается в пустышку (некому ничего отрендерить), либо тянет за собой полсистемы «на всякий случай». Фундамент делается быстро, после него срезы предсказуемы и независимы.

**Почему не backend-first или frontend-first целиком:** слишком долгий фидбек-луп, слишком много догадок про интеграцию, высокая вероятность переделок.

---

## 2. Отклонения от `technical_specifications.md`

### 2.1. Frontend stack (§6, §7)

Меняем UI-стек. Актуальные версии секций §6 и §7 уже обновлены в спеке — ниже суть изменения для истории решений.

| | Было (исходная спека) | Стало |
|---|---|---|
| Styling | TailwindCSS + shadcn/ui | **CSS modules + `global.css` + PostCSS** |
| Components | shadcn/ui (поверх Radix) | **Radix headless primitives напрямую** |
| Icons | (подразумевалось lucide через shadcn) | **`lucide-react` напрямую** |
| Декомпозиция | не фиксировалась | **Atomic design:** `atoms/` / `molecules/` / `organisms/` / `templates/` |
| Package manager | не фиксировалось | **pnpm** |

**Обоснование:** прототип (`mvp-ui-mock/app/ds/`) уже содержит цельную DS как набор CSS-токенов и компонент-примитивов. Tailwind поверх этого — лишний слой; shadcn — generic, который придётся перестилизовывать под токены прототипа всё равно. Прямой путь: портируем токены в `global.css`, базовые примитивы — в `atoms/` с `.module.css`, Radix берём только там, где реально нужна headless-логика (Dialog/Dropdown/Popover/Tooltip).

Остальной стек из §6 **сохраняется без изменений**: Zustand, TanStack Query, react-router, react-resizable-panels, `@uiw/react-md-editor`.

### 2.2. Миграции (§5)

Уточнение, не противоречащее спеке: используем простые версионированные `.sql` файлы + тонкий runner (не Alembic). Spec-side — это деталь реализации внутри `app/storage/db.py`, formal spec change не требуется.

---

## 3. Foundation phase — content

Цель: после завершения фундамента оба приложения (бэк + фронт) запускаются, проходят health-чек, в БД применены миграции и засеяны families. Никаких бизнес-фич ещё нет.

### 3.1. Backend

**Структура:**
```
backend/
├── pyproject.toml
├── app/
│   ├── main.py                  # FastAPI + /health
│   ├── config.py                # резолв ./data/ walk-up от app/main.py
│   ├── api/                     # пустой namespace с __init__.py (наполняется в slice'ах)
│   ├── services/                # пустой namespace с __init__.py (наполняется в slice'ах)
│   ├── storage/
│   │   ├── db.py                # sqlite + sqlite-vec, WAL, FK on, connection pool
│   │   ├── migrations.py        # runner для .sql файлов
│   │   ├── library_repo.py      # CRUD families/models/loras (raw)
│   │   ├── session_repo.py      # CRUD projects/sessions/messages/prompts (raw)
│   │   └── images.py            # file I/O helpers для data/images/
│   ├── models/                  # Pydantic schemas (namespace, пока пусто или базовые)
│   └── cli/
│       ├── init_db.py           # применяет миграции + сид families
│       └── reindex_all.py       # заглушка под Slice 5
├── migrations/
│   ├── 001_init.sql             # все таблицы из §3 спеки + индексы
│   └── 002_seed_families.sql    # 10 families (закрытый справочник)
└── tests/
    └── test_db_smoke.py         # миграции применяются, families засеяны, FK enforced
```

**Ключевые решения:**
- `schema_migrations(version INTEGER PK, applied_at INTEGER)` — тонкая таблица, runner читает файлы по возрастанию, применяет каждый недостающий файл **в отдельной транзакции** (BEGIN → exec script → INSERT в schema_migrations → COMMIT). По файлу — одна транзакция; это ограничивает blast radius частичного применения и корректно работает с `CREATE VIRTUAL TABLE` sqlite-vec.
- `001_init.sql` явно содержит **все** таблицы из §3 спеки, включая junction-таблицы: `families`, `models`, `loras`, `lora_family_compat`, `vec_loras` (virtual), `lora_vec_map`, `projects`, `sessions`, `session_pinned_loras`, `messages`, `prompts` + все индексы (`idx_sessions_project`, `idx_messages_session`, `idx_prompts_session`).
- `PRAGMA foreign_keys = ON` и `PRAGMA journal_mode = WAL` ставятся при каждом открытии соединения.
- `vec_loras` создаётся в той же миграции через `CREATE VIRTUAL TABLE ... USING vec0(embedding FLOAT[1024])`. Размерность 1024 зафиксирована под bge-m3 (§7 спеки).
- Resolver `./data/`: идёт вверх от `app/main.py` до каталога, содержащего `backend/` или `.git`, кладёт `data/` туда. Нет env-переменных (§2 спеки).
- Repositories возвращают dict-и / Pydantic-модели, не sqlite Row напрямую. API в фазе фундамента **не строится** — только репозитории.

**Seed families** (из `mvp-ui-mock/app/data.js`):
`sdxl`, `illustrious`, `pony`, `flux`, `sd15`, `sd21`, `cascade`, `hunyuan`, `kolors`, `auraflow` — с их `prompt_guide` дословно из мока.

### 3.2. Frontend

**Структура:**
```
frontend/
├── package.json                 # pnpm
├── vite.config.ts
├── postcss.config.js            # autoprefixer + postcss-nested
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx                 # ReactDOM + QueryClientProvider + RouterProvider
    ├── app.tsx                  # корневой layout wrapper
    ├── styles/
    │   ├── tokens.css           # портируем из mvp-ui-mock/app/ds/tokens.css
    │   ├── primitives.css       # портируем primitives
    │   └── global.css           # reset + импорты tokens/primitives
    ├── routes/
    │   ├── workspace.tsx        # /projects/:p/sessions/:s — плейсхолдер
    │   └── library/
    │       ├── families.tsx     # плейсхолдер
    │       ├── models.tsx       # плейсхолдер
    │       └── loras.tsx        # плейсхолдер
    ├── components/
    │   ├── atoms/               # Button, Icon, Badge (портируем из мока)
    │   ├── molecules/           # (пусто, наполняем по slice'ам)
    │   ├── organisms/           # (пусто, наполняем по slice'ам)
    │   └── templates/
    │       ├── AppShell.tsx     # Topbar + Sidebar + outlet
    │       ├── WorkspaceLayout.tsx
    │       └── LibraryLayout.tsx
    ├── store/                   # Zustand (базовый — пустой store)
    └── api/
        ├── client.ts            # fetch wrapper (base URL из env), QueryClient instance
        └── health.ts            # useHealth() хук; AppShell вызывает его и рисует connection dot
```

**Ключевые решения:**
- Иконки: обёртка `<Icon name="Folder" />` поверх `lucide-react`, дабы не импортировать весь lucide-pack на каждой странице. Имена из мока мапим на lucide-компоненты.
- Radix берём только по требованию. В фундаменте никаких Radix-компонентов пока нет.
- `AppShell` рендерит Topbar + Sidebar из мока (упрощённые версии, без реальной логики — просто видны).
- Роуты — валидные URL, внутри — placeholder-панели с подписью «coming in Slice N».
- TanStack Query: `QueryClient` создаётся в `main.tsx`, `QueryClientProvider` оборачивает всё.

### 3.3. Тулинг

- `pytest` настроен на `backend/tests/`, smoke-тест миграций
- `vitest` настроен на `frontend/src/`, минимальный sanity-тест на рендер AppShell
- README в корне с инструкциями: `pnpm install && pnpm dev`, `uv pip install -e backend && python -m app.cli.init_db && uvicorn app.main:app --reload`
- **CI пока не настраиваем** — сознательно откладываем, локальный проект
- **Lint/format:** `ruff` для Python (минимальный конфиг), `eslint` + `prettier` для фронта — всё на дефолтах

### 3.4. Что НЕ входит в Foundation

Следующее появляется в vertical slices, не в фундаменте:
- Любые API endpoints кроме `/health`
- Embedder / indexer / retriever / LLM / VL клиенты
- Реальные компоненты панелей (SourceImagePane, ChatPane, PromptPane, SessionDrawer)
- Library CRUD UI (страницы существуют, но пустые)
- Upload картинок
- Вёрстка Library таблиц

---

## 4. Vertical slices — порядок и границы

Каждый срез — отдельный план через `writing-plans` после завершения предыдущего. Границы срезов зафиксированы, чтобы planning-фаза каждого среза была коротким refinement'ом этого документа, а не заново-брейнштормом.

### Slice 1 — Library CRUD (без эмбеддинга)
- **Бэк:** REST endpoints `/api/library/families`, `/api/library/models`, `/api/library/loras` (GET list + filters, GET one, POST, PUT, DELETE). Репозитории уже готовы с фундамента — тут оборачиваем их в FastAPI routes с Pydantic-валидацией.
- **Фронт:** страницы `/library/families|models|loras` — таблицы + формы редактирования (md-editor для markdown-полей). Портируем из `mvp-ui-mock/app/library.jsx`.
- **Не входит:** эмбеддинги/`vec_loras` — добавим в Slice 5. На upsert'ах пишем только в основные таблицы.
- **Acceptance:** можно через UI создать family → model → lora и увидеть их в списке; данные переживают перезапуск бэка.

### Slice 2 — Projects & Sessions CRUD + source upload
- **Бэк:** `/api/projects` (GET/POST), `/api/sessions/...` (GET/POST/PATCH/DELETE), `/api/sessions/{s}/source` (POST upload → `data/images/<session_id>/source.<ext>`). Транзакционное удаление сессии (БД каскадно + файлы).
- **Фронт:** Sidebar с проектами/сессиями, workspace с пустыми панелями, SessionSettingsDrawer (model, use_negative, pinned LoRAs — мульти-селектор с уже существующими LoRA из Slice 1). Источник грузится drag-and-drop или через кнопку.
- **Не входит:** VL endpoints в drawer, vl_summary, chat, generate-prompt.
- **Acceptance:** создать проект → сессию → загрузить исходник → увидеть превью; переключаться между сессиями; удалить сессию → папка `data/images/<session_id>/` уходит вместе.

### Slice 3 — VL analyze-source
- **Бэк:** `app/services/vl_client.py` (OpenAI-compat обёртка), endpoint `/api/sessions/{s}/analyze-source`. Настраиваемые `vl_endpoint` (base_url, model, api_key) per session.
- **Фронт:** поле VL endpoint в SessionSettingsDrawer, кнопка Analyze в SourceImagePane, отображение `vl_summary`. Состояния: idle / analyzing / done / error.
- **Acceptance:** с настроенным LMStudio нажимаю Analyze → через N секунд вижу саммари; оно переживает перезапуск.

### Slice 4 — Chat SSE
- **Бэк:** `app/services/llm_client.py`, endpoint `/api/sessions/{s}/chat` (SSE). Per-session `prompt_endpoint`. Persist в `messages`.
- **Фронт:** ChatPane со стримингом (поток чанков → progressive render), история загружается при открытии сессии. Кнопка Generate prompt присутствует, но disabled (появится в Slice 6).
- **Не входит:** tool-calling, generate-prompt триггер через модель.
- **Acceptance:** можно вести диалог, сообщения стримятся, сохраняются в БД, история видна после reload.

### Slice 5 — Embedder + Indexer
- **Бэк:** `app/services/embedder.py` (sentence-transformers + bge-m3, lazy-load модели на первом использовании). `app/services/indexer.py` — hook на upsert/delete в library_repo, пересчитывает эмбеддинг и пишет в `vec_loras` + `lora_vec_map` в одной транзакции. CLI `reindex-all` — полная переиндексация.
- **Фронт:** (ничего — невидимая инфраструктура). Возможно, toast в LoraForm «indexing...» / «indexed».
- **Acceptance:** после создания/редактирования LoRA в `vec_loras` есть соответствующая строка; `reindex-all` пересчитывает все LoRA; после DELETE строка уходит.

### Slice 6 — Generate-prompt (двухступенчатый) — MVP done
- **Бэк:** `app/services/retriever.py` (top-K per intent через sqlite-vec), `app/services/prompt_builder.py` (сборка системного промпта из §4.5 спеки), endpoint `/api/sessions/{s}/generate-prompt`. Persist в `prompts` включая `intents_json` и `retrieved_loras_json`. Возврат inline + поддержка `GET /api/sessions/{s}/prompts` для истории.
- **Фронт:** PromptPane (positive / negative / LoRAs rows с слайдерами + бейджами pinned/retrieved/picked), Copy-кнопки (positive, negative, LoRA-string), debug-pane (intents → retrieved), pin/unpin LoRA inline, предупреждение для unknown LoRA. Кнопка Generate в ChatPane активна.
- **Acceptance:** полный флоу — upload → analyze → chat → generate → скопировать промпт → вставить в ComfyUI. Прошлые генерации доступны через историю.

После Slice 6 MVP (§9 спеки) закрыт. Post-MVP работы (VL-критика результата, tool-calling agent, импорт LoRA из .md) — отдельные проекты с собственными spec/plan.

---

## 5. Риски и открытые вопросы

**Риски:**
- **bge-m3 ~2GB на первый запуск** — честно описываем в README, возможно кэшируем в `data/models/` (не git). Если у пользователя VRAM-constrained, альтернатива `intfloat/multilingual-e5-base` через миграцию (не флаг) — но это пост-MVP.
- **sqlite-vec + Windows** — полагаемся на precompiled wheels с PyPI (§7 спеки). Если на конкретной машине не встанет — fallback на numpy brute-force подсчёт cosine поверх обычной TEXT-колонки, но это архитектурный откат, отмечаем как риск.
- **SSE + FastAPI + uvicorn под Windows** — обычно работает, но буферизация может ломаться. Проверяем в Slice 4, если что — переключаемся на `EventSourceResponse` из `sse-starlette`.

**Открытые вопросы (не блокируют фундамент):**
- Формат выбора VL/prompt endpoint в drawer — отдельное поле «вставь JSON» или форма из 3 инпутов (base_url, model, api_key)? Разруливаем в Slice 3.
- Куда кладутся скачанные веса эмбеддера — `~/.cache/huggingface/` (HF default) или `data/models/` (под наш data-root)? Разруливаем в Slice 5.

---

## 6. Deliverables фазы brainstorm

1. ✅ Правки §6 и §7 спеки (UI stack)
2. ✅ Этот документ
3. ➡️ План Foundation phase через `writing-plans` skill
