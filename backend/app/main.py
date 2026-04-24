from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.library import router as library_router

app = FastAPI(title="sd-chisel", version="0.0.1")

# Local dev: frontend runs on 5173 by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(library_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
