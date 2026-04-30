"""Backward-compat shim — re-exports everything from lmstudio_client.

Other modules (chat, sessions, prompt) still import ``lm_client``;
they will be migrated in a follow-up task. For now this keeps the app
importable without changing those files.
"""
from app.services.lmstudio_client import (  # noqa: F401
    DEFAULT_TIMEOUT,
    CHAT_TIMEOUT,
    LIST_TIMEOUT,
    LmError,
    LmsModel,
    analyze_image,
    chat_complete,
    chat_stream,
    list_models,
    unload_model,
)
