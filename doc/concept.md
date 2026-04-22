# sd-chisel — design & implementation plan

**Project name:** `sd-chisel`
**Location:** `F:\projects\sd-chisel\`


## Context

Мне нужен помощник для написания промптов для i2i генерации в Stable Diffusion
/ ComfyUI. Текущий флоу — ручной: смотрю на исходник, держу в голове нюансы
конкретной модели (SDXL/Pony/Flux/Illustrious), trigger-слова нужных LoRA,
желаемый стиль — и собираю промпт руками. Это медленно и ошибкоёмко.

Цель — инструмент, который берёт на себя три вещи:
1. Описывает исходное изображение (VL-модель) в терминах, полезных для
   последующей генерации.
2. Держит в контексте *мою* библиотеку LoRA и *мою* документацию по модели
   (как правильно промптить конкретно этот чекпоинт).
3. Ведёт со мной чат: я говорю, что хочу поменять — он отдаёт готовую пару
   positive/negative + рекомендуемые параметры.

Это отдельное локальное приложение, а не нода ComfyUI (итеративный чат плохо
ложится на граф). MVP не интегрируется с ComfyUI напрямую — финальный промпт
копирую сам. Задел под полный цикл (шаг 6: прогон результата через VL для
правок) закладываем в архитектуру, но в MVP не включаем.

---

## Architecture overview

```
┌────────────────────────────────────────────────────────────┐
│ Windows host                                               │
│                                                            │
│  ┌──────────────────┐       ┌──────────────────────────┐   │
│  │  React (Vite)    │ HTTP  │  FastAPI backend         │   │
│  │  4-panel UI      │◄─────►│  - sessions / projects   │   │
│  │  + chat stream   │  SSE  │  - LoRA & model docs     │   │
│  └──────────────────┘       │  - LLM client (OpenAI-   │   │
│                             │    compatible)           │   │
│                             └────────┬─────────────────┘   │
│                                      │                     │
│                                      ▼                     │
│                             ┌──────────────────┐           │
│                             │  LMStudio        │           │
│                             │  (VL + text LLM) │           │
│                             └──────────────────┘           │
│                                                            │
│  Data on disk:  <data_root>/projects/<project>/sessions/   │
│                 <data_root>/library/loras/*.md             │
│                 <data_root>/library/models/*.md            │
└────────────────────────────────────────────────────────────┘
```

- Бэкенд и фронт крутятся на Windows. LMStudio — тоже Windows (GPU). Никаких
  VM / туннелей. Это полностью отдельный от `study` проект.
- Связь фронта с бэком: REST для CRUD, SSE для стриминга ответов чата.
- Связь бэка с LMStudio: OpenAI-совместимый HTTP (и для VL, и для text).
  Endpoint/модель настраиваются **на уровне сессии** независимо для VL и
  "prompt writer".

---

## UI layout (одна основная страница)

```
┌─ Sidebar ─────┬─ Main workspace ──────────────────────────────────┐
│ Projects      │  ┌─ Source image ────┐ ┌─ Result image ─────────┐ │
│  ▸ Project A  │  │  drag&drop / paste │ │  drag&drop (step 6)    │ │
│  ▾ Project B  │  │  VL summary below  │ │  VL critique below     │ │
│    • Session1 │  └────────────────────┘ └────────────────────────┘ │
│    • Session2 │  ┌─ Chat ────────────────────────────────────────┐ │
│    + new      │  │ user/assistant messages, streaming            │ │
│               │  └────────────────────────────────────────────────┘│
│               │  ┌─ Generated prompt ────────────────────────────┐ │
│               │  │ [Positive]   [Negative]   [Params / LoRAs]    │ │
│               │  │ copy buttons, обновляется после каждой выдачи │ │
│               │  └────────────────────────────────────────────────┘│
├───────────────┤                                                    │
│ Library       │  Session settings (в шапке): model doc, активные   │
│  • LoRAs      │  LoRAs, VL endpoint, prompt-writer endpoint.       │
│  • Models     │                                                    │
└───────────────┴────────────────────────────────────────────────────┘
```

Окно "Result image" в MVP существует, но VL-критика отключена (placeholder) —
это и есть "задел под шаг 6".

---

## Data model (file-based, без БД)

Корень данных — одна папка, настраивается через env (`APP_DATA_DIR`, дефолт
`%APPDATA%\sd-chisel`):

```
<data_root>/
├── library/
│   ├── loras/
│   │   ├── detail-tweaker-xl.md     # описание, trigger, рек. вес, примеры
│   │   └── ...
│   └── models/
│       ├── sdxl-base.md             # правила промптинга для этой модели
│       ├── pony-v6.md
│       └── ...
├── projects/
│   └── <project-slug>/
│       ├── project.json             # name, created_at
│       └── sessions/
│           └── <session-id>/
│               ├── session.json     # настройки (модель, LoRAs, endpoints)
│               ├── messages.jsonl   # append-only лог чата
│               ├── source.<ext>     # исходная картинка
│               ├── result.<ext>     # результат (опц., под шаг 6)
│               └── prompts.jsonl    # история финальных промптов
└── config.json                      # глобальные настройки UI
```

**Почему JSONL для messages/prompts:** append-only, дешёвый rolling save,
нормально грузится за один `read`, легко чинить руками.

**Почему markdown для library:** пользователь правит в любом редакторе,
диффается в git (если захочет), бэкенд просто читает текст и кладёт в
системный промпт LLM. Никаких полей, которые нужно валидировать.

**Watcher:** бэк следит за `library/` через `watchdog` — при изменении .md
инвалидирует кеш. Не нужно перезапускать приложение после правки описания.

---

## Backend (Python)

- **Framework:** FastAPI + uvicorn.
- **LLM client:** `openai` SDK в OpenAI-compatible режиме
  (`base_url=http://localhost:1234/v1`, подходит и для LMStudio, и для внешних
  API, и для любого другого совместимого сервера).
- **Structured output:** для финального промпта (positive / negative /
  params / loras) — JSON schema через `response_format`. Фоллбэк на
  `instructor`-style парсинг, если сервер не умеет strict JSON.
- **Streaming:** чат-ответы стримим в SSE (`text/event-stream`), фронт —
  `EventSource`.
- **Endpoints (скетч):**
  - `GET  /api/projects`
  - `POST /api/projects`
  - `GET  /api/projects/{p}/sessions`
  - `POST /api/projects/{p}/sessions`
  - `GET  /api/sessions/{s}`
  - `PATCH /api/sessions/{s}` (настройки: модель, LoRAs, endpoints)
  - `POST /api/sessions/{s}/source` (upload картинки)
  - `POST /api/sessions/{s}/analyze-source` (VL → summary)
  - `POST /api/sessions/{s}/chat` (SSE)
  - `POST /api/sessions/{s}/generate-prompt` (structured JSON)
  - `GET  /api/library/loras`, `GET /api/library/models`
  - `POST /api/library/loras/{name}` (create/update .md)
  - Под шаг 6: `POST /api/sessions/{s}/result` + `analyze-result`.
- **Сборка системного промпта** (`services/prompt_builder.py`):
  - Берёт `models/<selected>.md` (правила промптинга для этого чекпоинта).
  - Для каждой активной LoRA — `loras/<name>.md`.
  - Текущий VL-summary исходника.
  - Последние N сообщений чата.
  - Инструкция: "верни JSON по такой-то схеме".
- **Единицы кода:** `api/` (роуты), `services/` (prompt_builder, llm_client,
  vl_client, sessions, library), `storage/` (чтение/запись файлов), `models/`
  (pydantic).

---

## Frontend (React)

- **Стек:** Vite + React + TypeScript + TailwindCSS + shadcn/ui.
- **State:** Zustand для клиентского состояния (активная сессия, настройки,
  локальные черновики) + TanStack Query для серверных данных.
- **Стриминг чата:** нативный `EventSource`.
- **Layout:** `react-resizable-panels` для 4-х панелей — удобнее, чем руками
  на CSS Grid.
- **Routing:** `react-router` — `/projects/:p/sessions/:s`, библиотека —
  `/library/loras`, `/library/models`.
- **Компоненты:**
  - `ChatPane`, `SourceImagePane`, `ResultImagePane`, `PromptPane`
    (positive / negative / params табы).
  - `SessionSettingsDrawer` — модель, LoRAs (мульти-чекбокс), endpoints.
  - `LibraryEditor` — markdown editor (`@uiw/react-md-editor`) для LoRA и
    model docs.
  - `ProjectSidebar`.

---

## Критические файлы, которые будут созданы

Новый отдельный репозиторий: `F:\projects\sd-chisel\`.

```
sd-chisel/
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py
│   │   ├── api/ (routes)
│   │   ├── services/ (prompt_builder, llm_client, vl_client, ...)
│   │   ├── storage/ (file I/O)
│   │   └── models/ (pydantic)
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes/
│   │   ├── components/
│   │   ├── stores/
│   │   └── api/ (fetch wrappers)
│   └── index.html
├── README.md
└── .env.example
```
