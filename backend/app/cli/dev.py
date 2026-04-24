"""CLI: run the local development API server.

Invoke:  uv run dev
"""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("app.main:app", reload=True, port=8000)


if __name__ == "__main__":
    main()
