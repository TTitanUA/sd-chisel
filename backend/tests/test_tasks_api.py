"""HTTP tests for the /api/tasks endpoints."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import task_runner


@pytest.fixture(autouse=True)
def _isolated_registry():
    async def _make() -> task_runner.TaskRegistry:
        return task_runner.TaskRegistry()

    reg = asyncio.run(_make())
    task_runner.install(reg)
    yield reg
    task_runner._install_for_tests(None)


def test_list_tasks_empty():
    client = TestClient(app)
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    assert resp.json() == {"tasks": []}


def test_list_tasks_returns_queued_task(_isolated_registry):
    _isolated_registry.submit(
        kind="reindex_lora",
        title="t",
        target={"lora_name": "x"},
        runner=lambda p: None,
    )
    client = TestClient(app)
    resp = client.get("/api/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["kind"] == "reindex_lora"
    assert body["tasks"][0]["status"] == "queued"
    assert body["tasks"][0]["target"] == {"lora_name": "x"}


def test_active_only_filter_endpoint(_isolated_registry):
    _isolated_registry.submit(
        kind="reindex_lora",
        title="t",
        target={"lora_name": "x"},
        runner=lambda p: None,
    )
    client = TestClient(app)
    resp = client.get("/api/tasks", params={"active_only": "false"})
    assert resp.status_code == 200
    assert len(resp.json()["tasks"]) == 1


# SSE stream behavior is exercised at the registry level by
# `test_subscribers_receive_lifecycle_events` in test_task_runner.py — the
# /api/tasks/stream endpoint is a thin SSE wrapper around `subscribe()`,
# and TestClient's streaming support hangs on the long-poll loop here.
