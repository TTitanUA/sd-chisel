# sd-chisel — technical specifications

**Статус:** брейнсторм-спека, фиксирует решения, принятые на стадии дизайна.
Supersedes технические разделы `doc/concept.md` (концепт оставлен как исходная
мотивация и prose-обоснование).

---

## 1. Цель и scope

Локальное Windows-приложение — помощник для написания промптов под i2i
генерацию в Stable Diffusion / ComfyUI. Берёт на себя:

1. Описание исходника VL-моделью в терминах, полезных для генерации.
2. Хранение *моей* библиотеки LoRA и моделей (чекпоинтов) с правилами
   промптинга.
3. Чат, в ходе которого агент сам подбирает подходящие LoRA из библиотеки и
   выдаёт готовые positive / negative / LoRA-строку.

**Не в MVP:** прямая интеграция с ComfyUI, VL-критика результата (шаг 6 —
задел в архитектуре, UI-плейсхолдер есть).

---

## 2. Архитектура (верхний уровень)

```
┌────────────────────────────────────────────────────────────────────┐
│ Windows host                                                       │
│                                                                    │
│  ┌─────────────────┐   HTTP    ┌────────────────────────────────┐  │
│  │ React (Vite)    │  + SSE    │ FastAPI backend                │  │
│  │ 4-panel UI      │◄─────────►│  - sessions / projects         │  │
│  │ + chat stream   │           │  - library CRUD (sqlite)       │  │
│  │ + library CRUD  │           │  - indexer (embed → sqlite-vec)│  │
│  └─────────────────┘           │  - retriever (top-K per intent)│  │
│                                │  - LLM client (OpenAI compat.) │  │
│                                │  - VL client                   │  │
│                                └───────┬────────────────────────┘  │
│                                        │                           │
│                                        ▼                           │
│                                ┌──────────────────┐                │
│                                │ LMStudio         │                │
│                                │ (VL + text LLM)  │                │
│                                └──────────────────┘                │
│                                                                    │
│ Data on disk:                                                      │
│   <data_root>/app.db                (sqlite: всё метаданные —      │
│                                      library + projects/sessions/  │
│                                      messages/prompts/pins)        │
│   <data_root>/images/<session_id>/source.<ext>, result.<ext>       │
│   <data_root>/config.json           (глобальные UI-настройки)      │
└────────────────────────────────────────────────────────────────────┘
```

- Фронт ↔ бэк: REST для CRUD, SSE для стриминга чата.
- Бэк ↔ LMStudio: OpenAI-совместимый HTTP. Endpoint и модель настраиваются
  **per-session** независимо для VL и prompt-writer.
- `<data_root>` — папка, настраивается через env (`APP_DATA_DIR`, дефолт
  `%APPDATA%\sd-chisel`).

---

## 3. Data model

Весь структурированный стейт — в одном файле `app.db` (sqlite + sqlite-vec).
Foreign keys включены (`PRAGMA foreign_keys = ON`), WAL-mode для конкурентных
read/write во время стриминга чата.

На диске вне БД остаются только бинарники (картинки) и глобальный
`config.json`.

### 3.1. Справочник / библиотека: семейства, модели, LoRA

```sql
-- Справочник семейств (закрытый, переиспользуется)
CREATE TABLE families (
  id            TEXT PRIMARY KEY,        -- 'sdxl', 'pony', 'illustrious', 'flux'
  display_name  TEXT NOT NULL,
  prompt_guide  TEXT NOT NULL,           -- базовый doc промптинга, LLM видит дословно
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

-- Чекпоинты
CREATE TABLE models (
  name          TEXT PRIMARY KEY,        -- имя файла без .safetensors
  display_name  TEXT NOT NULL,
  family_id     TEXT NOT NULL REFERENCES families(id) ON DELETE RESTRICT,
  description   TEXT,                    -- опц.; дельта-правила поверх family.prompt_guide
  author        TEXT,
  version       TEXT,
  source_url    TEXT,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

-- LoRA
CREATE TABLE loras (
  name                TEXT PRIMARY KEY,  -- имя для <lora:name:weight>
  display_name        TEXT NOT NULL,
  description         TEXT NOT NULL,     -- markdown, LLM видит дословно
  tags                TEXT NOT NULL DEFAULT '[]',   -- JSON array
  trigger_words       TEXT NOT NULL DEFAULT '[]',   -- JSON array
  recommended_weight  REAL,
  author              TEXT,
  version             TEXT,
  source_url          TEXT,
  created_at          INTEGER NOT NULL,
  updated_at          INTEGER NOT NULL
);

-- M:N совместимость LoRA ↔ семейства
CREATE TABLE lora_family_compat (
  lora_name  TEXT NOT NULL REFERENCES loras(name)  ON DELETE CASCADE,
  family_id  TEXT NOT NULL REFERENCES families(id) ON DELETE RESTRICT,
  PRIMARY KEY (lora_name, family_id)
);

-- Вектор-индекс
CREATE VIRTUAL TABLE vec_loras USING vec0(
  embedding FLOAT[768]                   -- размерность зависит от выбранной модели
);

-- Явная связка name ↔ rowid для vec_loras (sqlite-vec не даёт FK из virtual)
CREATE TABLE lora_vec_map (
  lora_name  TEXT PRIMARY KEY REFERENCES loras(name) ON DELETE CASCADE,
  rowid      INTEGER NOT NULL UNIQUE
);
```

**Соглашения:**

- `tags` и `trigger_words` — JSON-массивы, фильтрация через `json_each()`.
  Нормализация в junction-таблицы отложена до реальной потребности (статистика,
  производительность на 10K+ LoRA).
- Удаление LoRA → CASCADE в `lora_family_compat` и `lora_vec_map`; строку в
  `vec_loras` дропаем явно в той же транзакции.
- Удаление family блокируется RESTRICT, пока на него есть ссылки.
- `author`, `version`, `source_url` — всё опционально.

### 3.2. Проекты, сессии, чат, история промптов — в той же БД

```sql
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,       -- slug
  name        TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE sessions (
  id                 TEXT PRIMARY KEY,                   -- ulid/uuid
  project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name               TEXT,                               -- опц., юзерское
  model_name         TEXT REFERENCES models(name) ON DELETE SET NULL,
  use_negative       INTEGER NOT NULL DEFAULT 1,         -- 0/1
  vl_endpoint        TEXT,                               -- JSON {base_url, model, api_key}
  prompt_endpoint    TEXT,                               -- JSON
  vl_summary         TEXT,                               -- кешированный VL-анализ исходника
  source_image_path  TEXT,                               -- относит. <data_root>
  result_image_path  TEXT,                               -- опц., под шаг 6
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);
CREATE INDEX idx_sessions_project ON sessions(project_id, updated_at DESC);

-- Pinned LoRAs per session (обязательные, всегда в контексте)
CREATE TABLE session_pinned_loras (
  session_id       TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  lora_name        TEXT NOT NULL REFERENCES loras(name)  ON DELETE CASCADE,
  weight_override  REAL,                                 -- опц., overrides recommended_weight
  PRIMARY KEY (session_id, lora_name)
);

-- Append-only чат
CREATE TABLE messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content     TEXT NOT NULL,
  created_at  INTEGER NOT NULL
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- История финальных промптов (append-only)
CREATE TABLE prompts (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id            TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  positive              TEXT NOT NULL,
  negative              TEXT,                            -- NULL если use_negative = 0
  loras_json            TEXT NOT NULL,                   -- JSON [{name, weight}]
  intents_json          TEXT,                            -- debug: output шага intent rewriting
  retrieved_loras_json  TEXT,                            -- debug: что вернул retriever
  created_at            INTEGER NOT NULL
);
CREATE INDEX idx_prompts_session ON prompts(session_id, created_at);
```

**Соглашения:**

- `sessions.use_negative` — свойство воркфлоу (не модели). Если `0`, LLM
  возвращает `negative: null`.
- `sessions.vl_endpoint` / `prompt_endpoint` — JSON, независимые настройки
  для VL и prompt-writer вызовов (может быть разные base_url / модели).
- `session_pinned_loras` — обязательные LoRA, всегда добавляются в контекст
  LLM поверх retrieved. Мультивыбор в `SessionSettingsDrawer` пишет сюда.
- `prompts.intents_json` / `retrieved_loras_json` — для debug-pane и
  ретроспективы, ничего не блокируют.
- `sessions.source_image_path` / `result_image_path` — относительные пути к
  файлам на диске. Сами бинарники — отдельно.

### 3.3. Бинарники — на диске

```
<data_root>/images/<session_id>/
  ├── source.<ext>         # исходник
  └── result.<ext>          # результат (опц., под шаг 6)
```

Плоская структура по `session_id` (без вложения в проекты) — сессия сама по
себе уникальна, проект — это логическая группировка в БД. Удаление сессии
через API → каскадно чистит БД и удаляет папку `images/<session_id>/`.

---

## 4. LLM flows

### 4.1. `generate-prompt` — двухступенчатый

**Шаг 1 — intent rewriting.**

Вход: VL-summary исходника + последние N сообщений чата + агрегированный
список известных тегов (distinct `loras.tags`).

LLM выдаёт структурированный список интентов:

```json
{
  "intents": [
    { "kind": "style",     "query": "dramatic moody anime lighting" },
    { "kind": "detail",    "query": "fine detail enhancer" },
    { "kind": "character", "query": "red hair long" }
  ]
}
```

- `kind` — одно из известных тегов библиотеки (LLM получает этот список в
  системном промпте).
- `query` — поисковая фраза в терминах *эффекта*, не описания картинки.

**Шаг 2 — retrieval.**

Для каждого `intent` бэк:

1. Эмбеддит `query` через `sentence-transformers` (модель мультиязычная, см.
   §6).
2. Делает top-K по `vec_loras` (K ≈ 10–15 per intent), с опциональным
   pre-filter: `WHERE family_id = selected_model.family_id AND ... tag filter`.
3. Объединяет результаты, дедуплицирует по `lora_name`.

К этому набору добавляются все `pinned_loras` из session.

**Шаг 3 — prompt composition.**

Второй LLM-вызов. Получает:

- `family.prompt_guide` (базовые правила семейства).
- `model.description` (дельта, если не null).
- Полные `loras.description` для всех кандидатов (retrieved + pinned).
- VL-summary.
- Последние N сообщений чата.
- Инструкцию: "верни JSON по schema GeneratedPrompt".

Возвращает финальную схему (см. §4.4).

### 4.2. `analyze-source`

Единственный VL-вызов. На вход картинка + system-prompt "опиши изображение в
терминах, полезных для i2i генерации (композиция, стиль, освещение, объекты,
настроение)". Результат — свободный текст, сохраняется в session state и
используется во всех последующих вызовах.

### 4.3. `chat` (SSE)

Обычный стриминг-чат для обсуждения желаемых изменений. История кладётся в
`messages.jsonl`. Этот endpoint **не вызывает** generate-prompt — генерация
промпта инициируется отдельно пользователем (кнопкой) или модельным tool-call
(пост-MVP).

### 4.4. JSON schema финального промпта (`GeneratedPrompt`)

```json
{
  "positive": "string, required, non-empty",
  "negative": "string | null",
  "loras": [
    { "name": "string, required", "weight": "number, [-2.0, 2.0]" }
  ]
}
```

**Поведение:**

- `negative: null` — когда `session.use_negative = false`. Фронт прячет блок.
- LoRA с `name`, которого нет в таблице `loras`, — фронт показывает ⚠, но всё
  равно собирает строку `<lora:name:weight>` (lenient validation — LLM может
  предложить LoRA, которой у юзера нет, это полезный сигнал).
- `loras: []` допустимо.
- Параметры (sampler / cfg / steps / denoise / размеры / seed) в schema **не
  входят** — это забота юзера/ComfyUI.
- Пояснения "почему так" — обычным чат-сообщением ассистента, не в JSON.

Реализация: Pydantic-модель, LLM получает `response_format={"type":
"json_schema", "schema": ...}`. Фоллбэк — `instructor`-стиль парсинг
свободного текста, если сервер не умеет strict JSON.

### 4.5. Сборка системного промпта для `prompt composition`

```
{family.prompt_guide}

{model.description if not null}

# Available LoRAs
{loras[i].description                  # полный markdown, для каждого кандидата
 — separated by "---"}

# Source image analysis
{vl_summary}

# Conversation
{last N chat messages}

# Output
Return JSON matching this schema: {GeneratedPrompt schema}.
use_negative = {session.use_negative}  → если false, negative должен быть null.
```

Конфликты между `family.prompt_guide` и описанием конкретной LoRA разрешаются
в пользу LoRA (trigger-слова важнее общих правил) — это формулируется в самом
prompt_guide одной фразой.

---

## 5. Backend

**Стек:** Python 3.11+, FastAPI + uvicorn, Pydantic v2, `openai` SDK (для
LMStudio), `sentence-transformers`, `sqlite-vec`, `numpy`.

**Структура:**

```
backend/
├── pyproject.toml
├── app/
│   ├── main.py               # FastAPI entry
│   ├── api/
│   │   ├── projects.py
│   │   ├── sessions.py
│   │   ├── library.py        # CRUD families/models/loras
│   │   ├── chat.py           # SSE
│   │   └── prompt.py         # generate-prompt (двухступенчатый)
│   ├── services/
│   │   ├── llm_client.py     # OpenAI-compat обёртка
│   │   ├── vl_client.py
│   │   ├── embedder.py       # sentence-transformers
│   │   ├── indexer.py        # upsert → embedding → sqlite-vec
│   │   ├── retriever.py      # top-K per intent
│   │   ├── prompt_builder.py # сборка system prompt'а
│   │   └── sessions.py
│   ├── storage/
│   │   ├── db.py             # sqlite + sqlite-vec init, WAL, pool, migrations
│   │   ├── library_repo.py   # families/models/loras CRUD
│   │   ├── session_repo.py   # projects/sessions/messages/prompts CRUD
│   │   └── images.py         # file I/O для картинок (<data_root>/images/...)
│   └── models/               # Pydantic схемы (в т.ч. GeneratedPrompt, IntentList)
└── tests/
```

**Endpoints:**

- `GET /api/projects`, `POST /api/projects`
- `GET /api/projects/{p}/sessions`, `POST /api/projects/{p}/sessions`
- `GET /api/sessions/{s}`, `PATCH /api/sessions/{s}`
- `POST /api/sessions/{s}/source` (upload)
- `POST /api/sessions/{s}/analyze-source` (VL → summary)
- `POST /api/sessions/{s}/chat` (SSE)
- `POST /api/sessions/{s}/generate-prompt` (двухступенчатый, возвращает
  `GeneratedPrompt` + показывает промежуточные intents/retrieved через отдельные
  поля для debug-view)
- `GET /api/library/families`, `POST`, `PUT /{id}`, `DELETE /{id}`
- `GET /api/library/models`, `POST`, `PUT /{name}`, `DELETE /{name}`
- `GET /api/library/loras` (с фильтрами по tag, family_id), `POST`,
  `PUT /{name}`, `DELETE /{name}`
- Под шаг 6 (пост-MVP): `POST /api/sessions/{s}/result`, `analyze-result`.

**Индексер:**

- Срабатывает на любой `POST/PUT/DELETE` в `/api/library/loras`.
- Пересчитывает эмбеддинг для `description + tags + trigger_words` (join через
  разделитель), апсертит в `vec_loras` + `lora_vec_map` в одной транзакции.
- Reindex-all CLI-команда для миграций (смена модели эмбеддинга,
  пересборка).

---

## 6. Frontend

**Стек:** Vite + React 18 + TypeScript + TailwindCSS + shadcn/ui + Zustand
(клиентский стейт) + TanStack Query (серверные данные) + `react-router` +
`react-resizable-panels` + `@uiw/react-md-editor` (редактор для
description/prompt_guide).

**Экраны:**

- `/projects/:p/sessions/:s` — основная 4-панельная рабочая зона:
  `ProjectSidebar`, `SourceImagePane`, `ResultImagePane`,
  `ChatPane`, `PromptPane` (positive / negative / LoRA-строка — табы или
  стэк).
- `/library/families`, `/library/models`, `/library/loras` — CRUD-списки с
  поиском/фильтрами, форма редактирования (все markdown-поля в
  `react-md-editor`).
- `SessionSettingsDrawer` — выбор model + pinned LoRAs
  (мульти-чекбокс/тег-селектор) + endpoints (VL, prompt) + `use_negative`.

**PromptPane детали:**

- Positive / negative — две textarea, caption с символьным счётчиком.
- LoRA-список: строка на LoRA с бейджем `pinned / retrieved / picked`, слайдер
  веса, trigger-words из `loras` таблицы (если `name` неизвестен — ⚠ бейдж и
  вес-редактор без trigger-слов).
- Отдельная кнопка **Copy LoRA string** — собирает
  `<lora:a:0.6> <lora:b:0.8> ...`.
- Кнопки Copy positive / Copy negative — независимые.
- Debug-pane (опционально, свёрнут): intents → retrieved LoRAs → picked.

---

## 7. Внешние зависимости

**Бэк:**
- `fastapi`, `uvicorn[standard]`
- `pydantic` v2
- `openai` (для LMStudio OpenAI-compat)
- `sentence-transformers` (multilingual: кандидаты — `BAAI/bge-m3`,
  `intfloat/multilingual-e5-base`; финальный выбор на этапе имплементации)
- `sqlite-vec` (PyPI, precompiled binaries для Windows)
- `numpy`
- `python-multipart` (upload картинок)

**Без**: `langchain`, `llamaindex`, `watchdog`, `python-frontmatter`,
`chromadb` — обоснования см. выше. При появлении полноценного tool-calling
агента (пост-MVP) — рассмотрим `langgraph` точечно.

**Фронт:**
- `react`, `react-dom`, `vite`, `typescript`
- `tailwindcss`, `@radix-ui/*` (через shadcn/ui)
- `zustand`, `@tanstack/react-query`
- `react-router-dom`
- `react-resizable-panels`
- `@uiw/react-md-editor`

---

## 8. Репо-структура

```
sd-chisel/
├── README.md
├── .env.example
├── doc/
│   └── concept.md              # исходный prose-концепт
├── docs/
│   └── spec/
│       └── technical_specifications.md   # этот файл
├── backend/
│   ├── pyproject.toml
│   └── app/ ... (см. §5)
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/ ... (см. §6)
```

---

## 9. MVP scope / вне MVP

**В MVP:**
- Проекты + сессии (CRUD).
- Upload исходника, VL-анализ.
- Chat (SSE).
- Generate-prompt (двухступенчатый, intent rewriting + RAG retrieval +
  композиция).
- Library CRUD для families / models / loras (UI + REST).
- Индексер LoRA (автоматический на upsert).
- PromptPane с copy-кнопками.
- Pinned LoRAs, use_negative как session-settings.

**Вне MVP (задел в архитектуре):**
- VL-критика результата (шаг 6) — UI-плейсхолдер есть, endpoint-заглушка.
- Tool-calling агент (variant D из брейнсторма) — потенциально `langgraph`.
- Импорт LoRA из `.md`-папки (CLI) — отложен по решению на брейнсторме.
- Автоэкспорт БД в markdown-dump или снапшоты для git-истории.
- Шаринг описаний (export/import БД) как UI-фича.
- Нормализация `tags` / `trigger_words` в junction-таблицы — только если
  производительность/фичи потребуют.
- Статистика использования LoRA, рейтинги, "last used" трекинг.
