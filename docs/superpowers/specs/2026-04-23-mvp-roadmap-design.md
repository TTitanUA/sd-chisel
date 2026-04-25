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

### 2.3. LMStudio endpoint — глобальный, не per-session (правка от 2026-04-25)

Спека §3 описывает `sessions.vl_endpoint` / `sessions.prompt_endpoint` как JSON-колонки per session. На практике пользователь работает с одним LMStudio-инстансом, и хранение endpoint в каждой сессии бессмысленно дублирует данные и заставляет настраивать один и тот же URL в каждом drawer’е.

**Меняем:**

- Дропаем колонки `sessions.vl_endpoint` и `sessions.prompt_endpoint`.
- Добавляем синглтон-таблицу `app_settings(id=1, lmstudio_base_url, lmstudio_api_key, updated_at)`.
- Добавляем кеш-таблицу `lm_models(name PK, role IN ('vl','prompt','both'), enabled, last_seen)` — список моделей, доступных в LMStudio, с user-toggleable `enabled` и `role`.
- В сессии остаются только два указателя — `sessions.vl_model_name` и `sessions.prompt_model_name` (TEXT, no FK; `lm_models` — кеш, FK был бы хрупким).

**Почему отдельные `lm_models`, а не переиспользуем `models`:** в библиотеке `models` — это диффузные чекпоинты (Juggernaut, Pony и т.д.), сущность другого слоя. LMStudio-модели — это LLM/VL чат-completion модели; смешивать их в одной таблице путает.

**UI-следствия:** новый route group `/settings/lmstudio` со страницей конфига endpoint + кнопка *Refresh from LMStudio* + список моделей с тоглами. Drawer сессии теряет endpoint-инпуты, остаются два дропдауна (VL model / Prompt model) поверх enabled-моделей. Topbar показывает реальный host + connection dot вместо плейсхолдера.

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

Каждый срез — отдельный план через `writing-plans` после завершения предыдущего. Этот раздел задаёт **контракт между планами**: что срез получает на вход, какие границы обязан не пересекать, какой пользовательский сценарий доказывает готовность, и какой стабильный интерфейс остаётся следующему срезу.

**Dependency graph:** Foundation → Slice 1 → Slice 2 → Slice 3 → Slice 4 → Slice 5 → Slice 6. Порядок намеренно не оптимизирует “техническую чистоту”; он оптимизирует ранний end-to-end фидбек. Поэтому Embedder/Indexer идёт только в Slice 5: до generate-prompt векторный поиск не нужен, а Library, workspace, VL и chat должны стать живыми раньше.

**Общие правила для всех срезов:**
- После каждого среза оба приложения запускаются, `/health` работает, существующие пользовательские сценарии не ломаются.
- Каждый срез включает backend + frontend + tests/docs в том объёме, который нужен для его acceptance. “Только бэк” или “только фронт” допустимы только если это прямо указано как невидимая инфраструктура.
- API и storage contracts, появившиеся в срезе, считаются стабильными для следующих срезов. Если позже нужен breaking change, он оформляется как явная миграция/адаптер, а не тихая переделка.
- Внутри среза можно улучшать только те файлы и компоненты, которые срез реально использует. Широкий рефакторинг вне текущего пользовательского потока не входит.
- Acceptance всегда проверяется через UI-сценарий и через persistence/reload там, где есть состояние.

### Slice 1 — Library CRUD (без эмбеддинга)

**Предусловия:** Foundation завершён; БД создана, families засеяны, репозитории `library_repo.py` умеют читать/писать основные таблицы; фронтовые роуты `/library/families`, `/library/models`, `/library/loras` существуют как placeholder.

**Scope:**
- **Бэк:** REST endpoints `/api/library/families`, `/api/library/models`, `/api/library/loras`: list с фильтрами, get one, create, update, delete. Оборачиваем foundation-репозитории в FastAPI routes и Pydantic-схемы, добавляем нормальные 404/409/422.
- **Фронт:** страницы `/library/families|models|loras`: read-first таблицы, search/filter, формы create/edit, markdown-поля через `@uiw/react-md-editor`. Основной визуальный источник — `mvp-ui-mock/app/library.jsx`.
- **Storage:** только основные таблицы `families`, `models`, `loras`, `lora_family_compat`. `vec_loras` и `lora_vec_map` пока не трогаем.
- **Tests/docs:** API CRUD tests + минимальные UI/query tests на список и submit формы.

**Boundary:** нет embeddings, indexer hooks, similarity search, usage counts по сессиям, import/export библиотеки, batch operations.

**Acceptance:** через UI можно создать family → model → lora, открыть созданные записи в списках, отредактировать markdown-поле LoRA, удалить запись и увидеть изменение после перезапуска бэка/фронта.

**Handoff:** следующие срезы могут считать Library API стабильным источником families/models/loras; SessionSettingsDrawer в Slice 2 использует этот API для выбора model и pinned LoRAs.

### Slice 2 — Projects & Sessions CRUD + source upload

**Предусловия:** Slice 1 завершён; есть рабочая библиотека LoRA/model/family и API для чтения моделей/LoRA; workspace placeholder из Foundation доступен.

**Scope:**
- **Бэк:** `/api/projects` (list/create/update/delete), `/api/projects/{id}/sessions`, `/api/sessions/{id}` (get/patch/delete), `/api/sessions/{id}/source` (POST upload → `data/images/<session_id>/source.<ext>`), endpoint для отдачи source preview. `session_repo.delete(...)` удаляет сначала папку `data/images/<session_id>/`, потом БД-запись, чтобы не оставлять orphan files.
- **Фронт:** Sidebar с проектами/сессиями, создание проекта и сессии, переключение активной сессии, workspace layout с реальными пустыми панелями, `SourceImagePane` с drag-and-drop/choose file и preview, `SessionSettingsDrawer` с model, `use_negative`, pinned LoRAs.
- **Storage:** `projects`, `sessions`, `session_pinned_loras`; запись относительного `source_image_path`; каскадное удаление связанных rows.
- **Tests/docs:** upload/delete tests на БД + файловую систему, UI tests на создание сессии и отображение preview.

**Boundary:** нет VL-вызова, `vl_summary`, chat messages, prompt generation, result image workflow, ComfyUI-интеграции.

**Acceptance:** создать проект → создать сессию → выбрать model и pinned LoRAs → загрузить исходник → увидеть preview → переключиться на другую сессию и обратно → preview и настройки сохранились → удалить сессию → папка `data/images/<session_id>/` удалена.

**Handoff:** следующие срезы получают стабильный session workspace: active session, source image, session settings, pinned LoRAs и путь к файлу, пригодный для VL.

### Slice 3 — Settings + LMStudio + VL analyze-source

**Предусловия:** Slice 2 завершён; у сессии может быть source image; миграции 001/002 применены.

**Scope (см. §2.3 для архитектурного контекста):**

- **Backend storage (миграция 003):**
  - `ALTER TABLE sessions DROP COLUMN vl_endpoint`, `DROP COLUMN prompt_endpoint`.
  - `ALTER TABLE sessions ADD COLUMN vl_model_name TEXT`, `ADD COLUMN prompt_model_name TEXT`.
  - `CREATE TABLE app_settings(id PK CHECK(id=1), lmstudio_base_url, lmstudio_api_key, updated_at)`; стартовая строка с NULL-ами.
  - `CREATE TABLE lm_models(name PK, role CHECK(role IN ('vl','prompt','both')), enabled, last_seen)`.
- **Backend services:**
  - `app/services/lm_client.py` — OpenAI-compatible клиент: `list_models(endpoint)` (`GET /v1/models`) + `analyze_image(endpoint, model, image_bytes, content_type)` (`POST /v1/chat/completions` с vision payload). Принимает endpoint-конфиг как параметр (никаких глобальных импортов).
- **Backend API:**
  - `GET/PUT /api/settings/lmstudio` — base_url + api_key (api_key опционален).
  - `POST /api/settings/lmstudio/refresh` — пробит LMStudio через `list_models`, апсертит в `lm_models` (новые приходят с `enabled=1`, `role='both'`), не трогает существующие тогглы кроме `last_seen`. Возвращает обновлённый список или 502/504.
  - `GET /api/settings/lmstudio/models` — отдаёт кешированный `lm_models`.
  - `PATCH /api/settings/lmstudio/models/{name}` — меняет `enabled` и/или `role`.
  - `POST /api/sessions/{id}/analyze-source` — читает global config + `session.vl_model_name`, валидирует что модель есть в `lm_models` и enabled, вызывает `analyze_image`, сохраняет `vl_summary`. 409 если нет global config, нет source image, или нет/disabled `vl_model_name`.
  - `PATCH /api/sessions/{id}` принимает `vl_model_name` и `prompt_model_name`.
- **Frontend:**
  - Новая route group `/settings/*` с `SettingsLayout` (sidebar tabs; пока единственная вкладка — LMStudio).
  - Страница `/settings/lmstudio`: форма endpoint (base_url, api_key как password-инпут с подсказкой «может быть пустым для LMStudio»), кнопка *Refresh from LMStudio*. Секция моделей: пока config пустой или последний refresh упал — баннер «не подключено · нажмите Refresh» с явной ошибкой; иначе таблица с тоглами enabled и селектом role.
  - Сайдбар: gear-icon в футере → `Link` на `/settings/lmstudio`.
  - Topbar (`AppShell`): живой host + connection dot из `app_settings` + `useLmHealth()` (отдельный лёгкий ping-хук, отдельный от refresh — не дёргает /v1/models на каждый рендер).
  - Drawer сессии: убираем endpoint-инпуты; добавляем два `<select>` — VL model и Prompt model — над enabled `lm_models`, фильтрованных по role. Показ disabled-state с CTA «настроить в Settings», если список пуст.
  - `SourceImagePane`: меняем мета-строку на `VL · {session.vl_model_name ?? '(not set)'}`, кнопка Analyze дизейблится с понятным title пока (a) нет global config, (b) нет source image, (c) нет или disabled `vl_model_name`. Состояния idle/analyzing/done/error прежние.
- **Tests/docs:**
  - Repo tests: app_settings round-trip, lm_models upsert merge-without-clobber, sessions vl_model_name persists.
  - Service tests на `lm_client` с `httpx.MockTransport`: list_models, analyze_image, error-paths (timeout / non-2xx / shape).
  - API tests: settings CRUD, refresh-endpoint c monkeypatched lm_client, analyze-source гоняется через настоящий PATCH-цикл (set lmstudio → refresh → enable model → set vl_model_name на сессии → analyze).
  - UI tests: страница LMStudio (no-config баннер, refresh, тогглы), drawer (model dropdowns), SourceImagePane (disabled-state причины).

**Boundary:** chat, prompt composition, result-image, ComfyUI integration, инлайн-пикеры моделей в Chat/VL панелях (только в drawer), полноценные scheduled health-checks в фоне (только on-demand refresh + light ping).

**Acceptance:**

1. Открыл `/settings/lmstudio`, ввёл `base_url`, нажал Refresh → увидел список моделей; перезагрузил страницу → endpoint и тогглы сохранились.
2. Если LMStudio выключен — Refresh даёт явную ошибку, баннер «не подключено» остаётся, старый кеш `lm_models` не пропадает.
3. В drawer’е сессии — выбрал VL модель из enabled списка, сохранил → в шапке source-pane виден чип `VL · <model>`.
4. Нажал Analyze → loading → получил summary → перезагрузил страницу → summary остался.
5. Если на сессии не выбрана vl_model — Analyze disabled с понятным title; ошибка LMStudio не теряет предыдущий `vl_summary`.
6. Потоггалл модель в `enabled=false` и/или сменил role → drawer/dropdown сразу обновился (через invalidate query).

**Handoff:** Slice 4 (chat) и Slice 6 (generate-prompt) получают:
- Готовый global LMStudio config (читай через `settings_repo`).
- Список enabled `prompt`/`both` моделей и поле `session.prompt_model_name` для выбора per-session.
- `vl_summary` как стабильный текстовый контекст исходника.

### Slice 4 — Chat SSE

**Предусловия:** Slice 3 завершён; сессия содержит source image и может содержать `vl_summary`; в `sessions` есть `prompt_endpoint`; таблица `messages` существует.

**Scope:**
- **Бэк:** `app/services/llm_client.py` — OpenAI-compatible text client; `/api/sessions/{id}/chat` стримит SSE, сохраняет user/assistant messages в `messages`, включает в контекст `vl_summary`, последние N сообщений и session settings. `GET /api/sessions/{id}/messages` возвращает историю.
- **Фронт:** `ChatPane` со streaming render, optimistic user message, disabled/send states, загрузка истории при открытии сессии. Кнопка Generate prompt видна, но disabled с явным состоянием “available in Slice 6”.
- **Storage:** append-only `messages` с role/content/created_at; session `updated_at` обновляется при новом сообщении.
- **Tests/docs:** SSE contract test, fake LLM stream test, UI test progressive render/history reload.

**Boundary:** chat **не вызывает** generate-prompt; нет tool-calling, retriever, LoRA picking, prompt save, structured final prompt schema.

**Acceptance:** можно отправить сообщение, видеть assistant response чанками, закрыть/обновить страницу и увидеть историю; если LLM endpoint падает, user message не теряется, assistant error state не записывается как успешный ответ.

**Handoff:** Slice 6 получает стабильную историю сообщений и prompt endpoint settings; generate-prompt сможет использовать последние N сообщений без изменения chat API.

### Slice 5 — Embedder + Indexer

**Предусловия:** Slice 4 завершён; Library CRUD стабилен; `vec_loras` и `lora_vec_map` созданы Foundation-миграцией, но ещё не используются.

**Scope:**
- **Бэк:** `app/services/embedder.py` — lazy-load sentence-transformers + bge-m3; `app/services/indexer.py` — build embedding text из LoRA fields, upsert/delete vector rows, держит `loras` + `vec_loras` + `lora_vec_map` консистентными в одной операции. Library write endpoints вызывают indexer после create/update/delete. CLI `reindex-all` пересчитывает всю библиотеку.
- **Фронт:** минимальный статус в LoRA form/list: indexing/indexed/error, если это не раздувает API; иначе фронт только показывает обычный успех save.
- **Storage:** запись/удаление строк `vec_loras`, `lora_vec_map`; при ошибке indexer основная LoRA-запись не должна молча выглядеть “индексированной”.
- **Tests/docs:** unit tests на embedding text builder, indexer transaction tests, CLI smoke test с fake embedder, README note про первый запуск модели.

**Boundary:** нет retriever endpoint, нет generate-prompt UI, нет user-facing semantic search, нет альтернативной embedding-модели как runtime flag.

**Acceptance:** после create/update LoRA появляется/обновляется vector row; после delete vector row уходит; `reindex-all` пересчитывает все LoRA; при fake embedder тесты не требуют скачивания bge-m3.

**Handoff:** Slice 6 получает готовый vector index и внутренний API для top-K retrieval; Library CRUD теперь гарантирует актуальность индекса.

### Slice 6 — Generate-prompt (двухступенчатый) — MVP done

**Предусловия:** Slice 5 завершён; есть Library, sessions, source upload, VL summary, chat history, indexed LoRAs.

**Scope:**
- **Бэк:** `app/services/retriever.py` — top-K per intent через sqlite-vec; `app/services/prompt_builder.py` — сборка system prompt из §4.5 спеки; `/api/sessions/{id}/generate-prompt` выполняет двухступенчатый flow: intent extraction → retrieval + pinned LoRAs → prompt composition. Результат сохраняется в `prompts` с `positive`, `negative`, `loras_json`, `intents_json`, `retrieved_loras_json`; `GET /api/sessions/{id}/prompts` отдаёт историю.
- **Фронт:** `PromptPane`: positive/negative, LoRA rows со слайдерами и бейджами pinned/retrieved/picked/unknown, copy buttons для positive/negative/LoRA-string/all, debug pane intents → retrieved, regenerate, prompt history. Кнопка Generate в ChatPane активна.
- **Storage:** append prompts, сохранять unknown LoRA verbatim, не фильтровать модельный output сверх JSON/schema validation.
- **Tests/docs:** backend tests на two-step orchestration с fake LLM/retriever, prompt schema validation tests, UI tests на copy/debug/history, ручной smoke script полного MVP flow.

**Boundary:** нет ComfyUI API-интеграции, нет VL-критики результата, нет model tool-calling, нет импорта LoRA из `.md`, нет авто-регенерации после каждого chat message.

**Acceptance:** полный флоу работает руками: upload → analyze → chat → generate → увидеть structured prompt → скопировать positive/negative/LoRA-string → вставить в ComfyUI. Прошлые генерации доступны через историю после reload; unknown LoRA отображаются как warning, но не удаляются из результата.

**Handoff:** Slice 6 закрывает MVP (§9 спеки). Всё, что выходит за этот flow (VL-критика результата, tool-calling agent, импорт LoRA из .md, ComfyUI automation), оформляется как Post-MVP проект с отдельными spec/plan.

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
