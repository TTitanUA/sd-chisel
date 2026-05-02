from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import library_service, lora_reindex
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "api.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


@pytest.fixture
def client(conn, monkeypatch):
    """API client where reindex runs synchronously on the test connection.

    The HTTP route fires `lora_reindex.submit_reindex_lora(name)` after every
    create/update. In tests we want that work to complete before the response
    is read, so assertions on `is_indexed` see the post-reindex state — the
    actual async-task behaviour is covered by `test_lora_reindex.py`.
    """
    app.dependency_overrides[get_conn] = lambda: conn

    def _sync_reindex(name: str):
        # Mirror task_runner: per-row failures are swallowed (the row is
        # already committed; a failed embed marks the task failed, not the
        # HTTP request).
        try:
            library_service.reindex_one(conn, name)
        except Exception:  # noqa: BLE001
            pass
        return None

    monkeypatch.setattr(lora_reindex, "submit_reindex_lora", _sync_reindex)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_family_crud_http(client):
    create = client.post(
        "/api/library/families",
        json={
            "id": "api_fam",
            "display_name": "API Family",
            "prompt_guide": "Base guide",
            "prompt_i2i": "i2i specifics",
            "prompt_t2i": "t2i specifics",
        },
    )
    assert create.status_code == 201, create.json()
    body = create.json()
    assert body["id"] == "api_fam"
    assert body["prompt_i2i"] == "i2i specifics"
    assert body["prompt_t2i"] == "t2i specifics"

    # i2i/t2i are optional in create
    create2 = client.post(
        "/api/library/families",
        json={"id": "api_fam2", "display_name": "API Family 2", "prompt_guide": "Base"},
    )
    assert create2.status_code == 201, create2.json()
    assert create2.json()["prompt_i2i"] == ""
    assert create2.json()["prompt_t2i"] == ""

    duplicate = client.post(
        "/api/library/families",
        json={"id": "api_fam", "display_name": "API Family", "prompt_guide": "Guide"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/library/families", params={"q": "api"})
    assert listed.status_code == 200
    assert sorted(f["id"] for f in listed.json()) == ["api_fam", "api_fam2"]

    update = client.put(
        "/api/library/families/api_fam",
        json={
            "display_name": "API Family v2",
            "prompt_guide": "Base v2",
            "prompt_i2i": "",
            "prompt_t2i": "t2i v2",
        },
    )
    assert update.status_code == 200, update.json()
    assert update.json()["display_name"] == "API Family v2"
    assert update.json()["prompt_i2i"] == ""
    assert update.json()["prompt_t2i"] == "t2i v2"

    delete = client.delete("/api/library/families/api_fam")
    assert delete.status_code == 204
    assert client.get("/api/library/families/api_fam").status_code == 404


def test_model_crud_http_and_fk_conflict(client):
    missing_family = client.post(
        "/api/library/models",
        json={"name": "bad", "display_name": "Bad", "family_id": "missing"},
    )
    assert missing_family.status_code == 409

    create = client.post(
        "/api/library/models",
        json={
            "name": "juggernaut",
            "display_name": "Juggernaut",
            "family_id": "sdxl",
            "description": "General SDXL model",
        },
    )
    assert create.status_code == 201
    assert create.json()["family_id"] == "sdxl"

    listed = client.get("/api/library/models", params={"family_id": "sdxl", "q": "general"})
    assert [m["name"] for m in listed.json()] == ["juggernaut"]

    update = client.put(
        "/api/library/models/juggernaut",
        json={
            "display_name": "Juggernaut XL",
            "family_id": "sdxl",
            "description": "Updated",
            "author": "RunDiffusion",
            "version": "v10",
            "source_url": "https://example.test/juggernaut",
        },
    )
    assert update.status_code == 200
    assert update.json()["version"] == "v10"

    assert client.delete("/api/library/models/juggernaut").status_code == 204
    assert client.delete("/api/library/models/juggernaut").status_code == 404


def test_lora_crud_http(client):
    create = client.post(
        "/api/library/loras",
        json={
            "name": "cinematic_light",
            "display_name": "Cinematic Light",
            "description": "Rim light and cinematic contrast.",
            "tags": ["light", "mood"],
            "trigger_words": ["cinematic light"],
            "family_id": "sdxl",
            "recommended_weight": 0.8,
            "author": "me",
        },
    )
    assert create.status_code == 201
    assert create.json()["tags"] == ["light", "mood"]

    listed = client.get("/api/library/loras", params={"family_id": "sdxl", "tag": "light"})
    assert [row["name"] for row in listed.json()] == ["cinematic_light"]

    update = client.put(
        "/api/library/loras/cinematic_light",
        json={
            "display_name": "Cinematic Light 2",
            "description": "Softer cinematic light.",
            "tags": ["light"],
            "trigger_words": ["soft cinematic light"],
            "family_id": "sdxl",
            "recommended_weight": 0.65,
            "author": "me",
            "version": "v2",
            "source_url": None,
        },
    )
    assert update.status_code == 200
    assert update.json()["recommended_weight"] == 0.65

    assert client.delete("/api/library/loras/cinematic_light").status_code == 204
    assert client.get("/api/library/loras/cinematic_light").status_code == 404


from app.services import embedder


def _make_lora_payload(**override):
    base = {
        "name": "cinelight",
        "display_name": "Cinematic Light",
        "description": "dramatic rim light",
        "tags": ["light"],
        "trigger_words": ["cinematic"],
        "family_id": "sdxl",
        "recommended_weight": 0.8,
        "author": None,
        "version": None,
        "source_url": None,
    }
    base.update(override)
    return base


def test_create_lora_returns_is_indexed_false_until_reindex(client):
    """POST returns the row state at write time — the reindex hasn't run yet.
    The follow-up GET reflects the post-reindex state.
    """
    resp = client.post("/api/library/loras", json=_make_lora_payload())
    assert resp.status_code == 201
    assert resp.json()["is_indexed"] is False
    # After the synchronous fixture reindex (mirrors background task), the
    # next read sees the indexed state.
    assert client.get("/api/library/loras/cinelight").json()["is_indexed"] is True


def test_list_loras_includes_is_indexed_for_each_row(client):
    client.post("/api/library/loras", json=_make_lora_payload(name="a"))
    client.post("/api/library/loras", json=_make_lora_payload(name="b"))
    rows = client.get("/api/library/loras").json()
    assert {r["name"]: r["is_indexed"] for r in rows} == {"a": True, "b": True}


def test_get_lora_includes_is_indexed(client):
    client.post("/api/library/loras", json=_make_lora_payload(name="z"))
    body = client.get("/api/library/loras/z").json()
    assert body["is_indexed"] is True


def test_update_lora_drops_index_then_reindexes(client):
    client.post("/api/library/loras", json=_make_lora_payload())
    resp = client.put(
        "/api/library/loras/cinelight",
        json={
            "display_name": "Cinematic Light 2",
            "description": "more drama",
            "tags": ["light"],
            "trigger_words": ["cinematic"],
            "family_id": "sdxl",
            "recommended_weight": 0.85,
            "author": None, "version": None, "source_url": None,
        },
    )
    assert resp.status_code == 200
    # PUT response reflects post-write/pre-reindex state — vector dropped.
    assert resp.json()["is_indexed"] is False
    # Subsequent GET sees the post-reindex state (synchronous in tests).
    assert client.get("/api/library/loras/cinelight").json()["is_indexed"] is True


def test_delete_lora_removes_vector_too(client, conn):
    client.post("/api/library/loras", json=_make_lora_payload())
    assert client.delete("/api/library/loras/cinelight").status_code == 204
    assert conn.execute(
        "SELECT COUNT(*) FROM lora_vec_map WHERE lora_name = 'cinelight'",
    ).fetchone()[0] == 0


def test_list_loras_respects_global_show_hidden(client, conn):
    from app.storage import settings_repo
    client.post("/api/library/loras", json=_make_lora_payload(name="visible"))
    client.post("/api/library/loras", json=_make_lora_payload(name="secret"))
    client.patch("/api/library/loras/secret/hidden", json={"hidden": True})

    settings_repo.set_privacy(conn, show_hidden=False)
    names_off = sorted(r["name"] for r in client.get("/api/library/loras").json())
    assert names_off == ["visible"]

    settings_repo.set_privacy(conn, show_hidden=True)
    names_on = sorted(r["name"] for r in client.get("/api/library/loras").json())
    assert names_on == ["secret", "visible"]


def test_create_lora_keeps_row_when_embedder_fails(client, conn, monkeypatch):
    """Embed failures no longer roll back the LoRA write — the row commits,
    `is_indexed` stays false, and the task layer surfaces the error.
    """
    def boom(_text):
        raise embedder.EmbedderError("simulated embedder failure")

    monkeypatch.setattr(embedder, "embed", boom)

    resp = client.post("/api/library/loras", json=_make_lora_payload(name="oops"))
    assert resp.status_code == 201
    assert resp.json()["is_indexed"] is False
    assert conn.execute(
        "SELECT COUNT(*) FROM loras WHERE name = 'oops'",
    ).fetchone()[0] == 1


def test_lora_create_rejects_is_indexed_in_body(client):
    payload = _make_lora_payload()
    payload["is_indexed"] = True
    resp = client.post("/api/library/loras", json=payload)
    assert resp.status_code == 422


def test_rename_lora_http_success(client, conn):
    client.post("/api/library/loras", json=_make_lora_payload())
    resp = client.post(
        "/api/library/loras/cinelight/rename",
        json={"new_name": "cinelight_v2"},
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["name"] == "cinelight_v2"
    assert resp.json()["is_indexed"] is True
    assert client.get("/api/library/loras/cinelight").status_code == 404
    assert client.get("/api/library/loras/cinelight_v2").status_code == 200
    assert conn.execute(
        "SELECT COUNT(*) FROM lora_vec_map WHERE lora_name = 'cinelight_v2'",
    ).fetchone()[0] == 1


def test_rename_lora_http_not_found(client):
    resp = client.post(
        "/api/library/loras/ghost/rename",
        json={"new_name": "ghost2"},
    )
    assert resp.status_code == 404


def test_rename_lora_http_conflict(client):
    client.post("/api/library/loras", json=_make_lora_payload(name="a_lora"))
    client.post("/api/library/loras", json=_make_lora_payload(name="b_lora"))
    resp = client.post(
        "/api/library/loras/a_lora/rename",
        json={"new_name": "b_lora"},
    )
    assert resp.status_code == 409


def test_rename_model_http_success(client, conn):
    client.post("/api/library/models", json={
        "name": "old_ckpt",
        "display_name": "Old",
        "family_id": "sdxl",
    })
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) "
        "VALUES ('p1', 'P', 1, 1)",
    )
    conn.execute(
        "INSERT INTO sessions(id, project_id, model_name, created_at, updated_at) "
        "VALUES ('s1', 'p1', 'old_ckpt', 1, 1)",
    )

    resp = client.post(
        "/api/library/models/old_ckpt/rename",
        json={"new_name": "new_ckpt"},
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["name"] == "new_ckpt"
    assert client.get("/api/library/models/old_ckpt").status_code == 404
    assert conn.execute(
        "SELECT model_name FROM sessions WHERE id = 's1'",
    ).fetchone()["model_name"] == "new_ckpt"


def test_rename_model_http_not_found(client):
    resp = client.post(
        "/api/library/models/ghost/rename",
        json={"new_name": "ghost2"},
    )
    assert resp.status_code == 404


def test_rename_model_http_conflict(client):
    client.post("/api/library/models", json={
        "name": "a_ckpt", "display_name": "A", "family_id": "sdxl",
    })
    client.post("/api/library/models", json={
        "name": "b_ckpt", "display_name": "B", "family_id": "sdxl",
    })
    resp = client.post(
        "/api/library/models/a_ckpt/rename",
        json={"new_name": "b_ckpt"},
    )
    assert resp.status_code == 409


def test_rename_model_http_bad_slug(client):
    client.post("/api/library/models", json={
        "name": "ckpt_x", "display_name": "X", "family_id": "sdxl",
    })
    resp = client.post(
        "/api/library/models/ckpt_x/rename",
        json={"new_name": "bad name"},
    )
    assert resp.status_code == 422


def test_rename_lora_http_bad_slug(client):
    client.post("/api/library/loras", json=_make_lora_payload())
    resp = client.post(
        "/api/library/loras/cinelight/rename",
        json={"new_name": "bad name with spaces"},
    )
    assert resp.status_code == 422


import json

from app.services import lmstudio_client


def _parse_assist_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        for part in block.split("\n"):
            if part.startswith("data:"):
                events.append(json.loads(part[len("data:"):].strip()))
    return events


def test_assist_streams_text_and_artifact_via_function_call(client, conn, monkeypatch):
    """Model emits text delta + function_call(update_prompt_guide). Backend
    yields delta + artifact, then sends function_call_output, then receives a
    final completion."""
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "tool-model", "vision": False, "tool_use": True, "reasoning": False},
    ])

    pass_no = {"i": 0}

    def fake_stream(**kwargs):
        pass_no["i"] += 1
        if pass_no["i"] == 1:
            return iter([
                {"type": "delta", "content": "Sure, let me write it."},
                {"type": "function_call",
                 "call_id": "call_1", "name": "update_prompt_guide",
                 "arguments": {"content": "# Guide\nUse tags."}},
                {"type": "completed", "response_id": "resp_1"},
            ])
        # second pass — model finalises after receiving function_call_output
        return iter([
            {"type": "delta", "content": "Done!"},
            {"type": "completed", "response_id": "resp_2"},
        ])

    monkeypatch.setattr(lmstudio_client, "chat_responses_stream", fake_stream)

    resp = client.post(
        "/api/library/families/assist",
        json={"model": "tool-model", "message": "help me write a guide"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_assist_sse(resp.text)
    types = [e["type"] for e in events]
    assert "delta" in types
    assert "artifact" in types
    assert "done" in types

    artifact = next(e for e in events if e["type"] == "artifact")
    assert artifact["content"] == "# Guide\nUse tags."
    assert artifact["field"] == "prompt_guide"

    done = next(e for e in events if e["type"] == "done")
    # last response id from second pass
    assert done["response_id"] == "resp_2"


@pytest.mark.parametrize(
    "tool_name,expected_field",
    [
        ("update_prompt_i2i", "prompt_i2i"),
        ("update_prompt_t2i", "prompt_t2i"),
    ],
)
def test_assist_artifact_field_maps_to_tool_name(
    client, conn, monkeypatch, tool_name, expected_field
):
    """The artifact SSE event's `field` must reflect which update_* tool fired."""
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "tool-model", "vision": False, "tool_use": True, "reasoning": False},
    ])

    pass_no = {"i": 0}

    def fake_stream(**kwargs):
        pass_no["i"] += 1
        if pass_no["i"] == 1:
            return iter([
                {"type": "function_call",
                 "call_id": "call_1", "name": tool_name,
                 "arguments": {"content": "body"}},
                {"type": "completed", "response_id": "resp_1"},
            ])
        return iter([{"type": "completed", "response_id": "resp_2"}])

    monkeypatch.setattr(lmstudio_client, "chat_responses_stream", fake_stream)

    resp = client.post(
        "/api/library/families/assist",
        json={"model": "tool-model", "message": "go"},
    )
    assert resp.status_code == 200

    events = _parse_assist_sse(resp.text)
    artifact = next(e for e in events if e["type"] == "artifact")
    assert artifact["content"] == "body"
    assert artifact["field"] == expected_field


def test_assist_sends_function_call_output_on_followup(client, conn, monkeypatch):
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "tool-model", "vision": False, "tool_use": True, "reasoning": False},
    ])

    captures: list[dict] = []

    def fake_stream(**kwargs):
        captures.append(kwargs)
        if len(captures) == 1:
            return iter([
                {"type": "function_call",
                 "call_id": "call_X", "name": "update_prompt_guide",
                 "arguments": {"content": "# Guide"}},
                {"type": "completed", "response_id": "resp_A"},
            ])
        return iter([{"type": "completed", "response_id": "resp_B"}])

    monkeypatch.setattr(lmstudio_client, "chat_responses_stream", fake_stream)

    resp = client.post(
        "/api/library/families/assist",
        json={
            "model": "tool-model",
            "message": "go",
            "previous_response_id": "resp_prev",
        },
    )
    assert resp.status_code == 200

    # First pass: tools (function + mcp) + previous_response_id from request
    first = captures[0]
    assert first["previous_response_id"] == "resp_prev"
    # Snapshot block is prepended to the user message on the first pass.
    assert "Current editor state:" in first["user_input"]
    assert first["user_input"].endswith("---\ngo")
    assert any(t.get("name") == "update_prompt_guide" for t in first["tools"])
    assert any(
        t.get("type") == "mcp" and t.get("server_label") == "playwright"
        for t in first["tools"]
    )

    # Second pass: function_call_output + previous_response_id from first pass
    second = captures[1]
    assert second["previous_response_id"] == "resp_A"
    assert isinstance(second["user_input"], list)
    assert second["user_input"][0]["type"] == "function_call_output"
    assert second["user_input"][0]["call_id"] == "call_X"


def test_assist_forwards_tool_status(client, conn, monkeypatch):
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "tool-model", "vision": False, "tool_use": True, "reasoning": False},
    ])

    fake_events = [
        {"type": "tool_status", "tool": "browser_navigate", "status": "running"},
        {"type": "tool_status", "tool": "browser_navigate", "status": "done"},
        {"type": "delta", "content": "Done."},
        {"type": "completed", "response_id": "resp_X"},
    ]

    monkeypatch.setattr(lmstudio_client, "chat_responses_stream", lambda **_: iter(fake_events))

    resp = client.post(
        "/api/library/families/assist",
        json={"model": "tool-model", "message": "read this url"},
    )
    events = _parse_assist_sse(resp.text)
    tool_events = [e for e in events if e["type"] == "tool_status"]
    assert len(tool_events) == 2
    assert tool_events[0]["status"] == "running"


def test_assist_rejects_model_without_tool_use(client, conn):
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "no-tools", "vision": False, "tool_use": False, "reasoning": False},
    ])

    resp = client.post(
        "/api/library/families/assist",
        json={"model": "no-tools", "message": "help"},
    )
    assert resp.status_code == 409
    assert "tool use" in resp.json()["detail"]
