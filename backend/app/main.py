from mimetypes import guess_type

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app import config as app_config
from app.api.chat import router as chat_router
from app.api.library import router as library_router
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router

app = FastAPI(title="sd-chisel", version="0.0.1")

# Local dev: frontend runs on 5173 by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(library_router)
app.include_router(sessions_router)
app.include_router(settings_router)

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
