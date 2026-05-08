import logging
from contextlib import asynccontextmanager
from mimetypes import guess_type

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app import config as app_config
from app.api.chat import router as chat_router
from app.api.comfy import router as comfy_router
from app.api.library import router as library_router
from app.api.prompt import router as prompt_router
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router
from app.api.tasks import router as tasks_router
from app.services import lora_reindex, task_runner
from app.storage import db as db_mod
from app.storage.migrations import DEFAULT_MIGRATIONS_DIR, apply_pending

logger = logging.getLogger(__name__)


def _apply_pending_migrations() -> None:
    """Bring ``data/app.db`` up to the current schema before any
    request handler or background task touches it. Failures here are
    fatal — re-raise so uvicorn aborts startup rather than serving on a
    half-migrated DB."""
    conn = db_mod.connect()
    try:
        count = apply_pending(conn, DEFAULT_MIGRATIONS_DIR)
        if count:
            logger.info(
                "applied %d pending migration(s) at startup (db=%s)",
                count, db_mod.db_path(),
            )
        else:
            logger.debug("schema is up to date (db=%s)", db_mod.db_path())
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations first — every other startup hook below assumes the
    # schema matches the code that's about to run.
    _apply_pending_migrations()
    registry = task_runner.TaskRegistry()
    registry.start()
    task_runner.install(registry)
    try:
        queued = lora_reindex.sweep_unindexed()
        if queued:
            logger.info("queued %d unindexed LoRAs at startup", queued)
    except Exception:  # noqa: BLE001 — startup sweep must not block boot
        logger.exception("startup reindex sweep failed")
    try:
        yield
    finally:
        await registry.stop()
        task_runner._install_for_tests(None)


app = FastAPI(title="sd-chisel", version="0.0.1", lifespan=lifespan)

# Local dev: frontend runs on 5173 by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(comfy_router)
app.include_router(library_router)
app.include_router(prompt_router)
app.include_router(sessions_router)
app.include_router(settings_router)
app.include_router(tasks_router)

_data_root = app_config.resolve_data_root()
(_data_root / "images").mkdir(parents=True, exist_ok=True)


@app.get("/media/images/{file_path:path}", include_in_schema=False)
def serve_data_image(file_path: str) -> FileResponse:
    """Serve files under `data/images/`; resolves at request time so tests can
    override `resolve_data_root` via monkeypatch (vs a fixed StaticFiles mount)."""
    base = (app_config.resolve_data_root() / "images").resolve()
    try:
        full = (base / file_path).resolve()
    except OSError as exc:  # pragma: no cover
        raise HTTPException(status_code=404, detail="not found") from exc
    if not str(full).startswith(str(base)) or not full.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media, _ = guess_type(str(full))
    return FileResponse(str(full), media_type=media or "application/octet-stream")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
