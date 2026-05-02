from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import prompt_orchestrator
from app.services.lmstudio_client import LmError
from app.storage import db as db_mod
from app.storage import library_repo, session_repo, settings_repo, source_image_repo
from app.storage.migrations import apply_pending


def _seed_main_image(conn, session_id: str, *, analysis: str = "moody girl, dramatic"):
    img = source_image_repo.insert(
        conn,
        session_id=session_id,
        path=f"images/{session_id}/sources/main.png",
        original_filename="main.png",
        is_main=True,
    )
    source_image_repo.set_analysis(
        conn, img["id"], analysis=analysis, refining_prompt=None,
    )
    return img


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


@pytest.fixture
def session_id(conn) -> str:
    fam = library_repo.get_family(conn, "sdxl")
    assert fam is not None
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl",
        description="model delta",
    )
    library_repo.create_lora(
        conn, name="lora-a", display_name="lora-a",
        description="A description", tags=["style"], trigger_words=["a_t"],
        family_id="sdxl",
    )
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(
        conn, project_id=proj["id"], name="s", model_name="m1",
    )
    _seed_main_image(conn, sess["id"])
    return sess["id"]


def _fake_lm_responses(intent_payload: str, composition_payload: str):
    calls = {"i": 0}
    def fake(*, endpoint, model, messages, response_format=None, transport=None):
        calls["i"] += 1
        if calls["i"] == 1:
            return intent_payload
        return composition_payload
    return fake


def test_generate_returns_persisted_response(conn, session_id, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete",
        _fake_lm_responses(
            intent_payload=json.dumps({"intents": [
                {"kind": "style", "query": "moody"},
            ]}),
            composition_payload=json.dumps({
                "positive": "moody girl, dramatic",
                "negative": "blurry",
                "loras": [{"name": "lora-a", "weight": 0.6}],
            }),
        ),
    )

    out = prompt_orchestrator.generate(
        conn,
        session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )

    assert out["prompt"]["positive"] == "moody girl, dramatic"
    assert out["prompt"]["negative"] == "blurry"
    assert out["prompt"]["loras"] == [{"name": "lora-a", "weight": 0.6}]
    assert out["intents"] == [{"kind": "style", "query": "moody"}]
    rows = session_repo.list_prompts(conn, session_id=session_id)
    assert rows[0]["positive"] == "moody girl, dramatic"


def test_generate_with_brief_replaces_chat_history(conn, session_id, monkeypatch):
    """When brief is provided, intent + composition payloads contain a
    `# User brief` block sourced from the brief and *no* chat history block."""
    session_repo.append_message(conn, session_id=session_id, role="user", content="ignored chat noise")
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: list[list[dict]] = []

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured.append(messages)
        if len(captured) == 1:
            return json.dumps({"intents": [{"kind": "style", "query": "noir"}]})
        return json.dumps({
            "positive": "noir mood", "negative": "blurry",
            "loras": [{"name": "lora-a", "weight": 0.6}],
        })

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete",
        fake_complete,
    )

    out = prompt_orchestrator.generate(
        conn,
        session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
        brief="moody noir cinematic, low key lighting",
    )
    assert out["prompt"]["positive"] == "noir mood"
    intent_user_msg = captured[0][1]["content"]
    composition_system_msg = captured[1][0]["content"]
    assert "# User brief\nmoody noir cinematic, low key lighting" in intent_user_msg
    assert "# Recent conversation" not in intent_user_msg
    assert "ignored chat noise" not in intent_user_msg
    assert "# User brief\nmoody noir cinematic, low key lighting" in composition_system_msg
    assert "# Conversation" not in composition_system_msg


def test_generate_use_negative_false_forces_null(conn, session_id, monkeypatch):
    session_repo.update_session(
        conn, session_id, name="s", model_name="m1",
        use_negative=False,
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete",
        _fake_lm_responses(
            intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
            composition_payload=json.dumps({
                "positive": "p", "negative": "", "loras": [],
            }),
        ),
    )
    out = prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert out["prompt"]["negative"] is None


def test_generate_use_negative_true_rejects_null_negative(conn, session_id, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete",
        _fake_lm_responses(
            intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
            composition_payload=json.dumps({
                "positive": "p", "negative": None, "loras": [],
            }),
        ),
    )
    with pytest.raises(LmError) as exc:
        prompt_orchestrator.generate(
            conn, session_id=session_id,
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
    assert exc.value.kind == "shape"


def test_generate_recovers_from_extra_prose_around_json(conn, session_id, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete",
        _fake_lm_responses(
            intent_payload=(
                'Here are the intents:\n'
                '{"intents": [{"kind":"k","query":"q"}]}\nHope this helps.'
            ),
            composition_payload=json.dumps({
                "positive": "p", "negative": "n", "loras": [],
            }),
        ),
    )
    out = prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert out["intents"][0]["query"] == "q"


def test_generate_raises_when_main_image_has_no_analysis(conn, session_id, monkeypatch):
    conn.execute(
        "UPDATE session_source_images SET analysis = NULL WHERE session_id = ?",
        (session_id,),
    )
    with pytest.raises(prompt_orchestrator.PreconditionError) as exc:
        prompt_orchestrator.generate(
            conn, session_id=session_id,
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
    assert "main source image" in str(exc.value) or "analysis" in str(exc.value)


def test_generate_raises_when_session_has_no_source_images(conn, session_id, monkeypatch):
    conn.execute(
        "DELETE FROM session_source_images WHERE session_id = ?", (session_id,),
    )
    with pytest.raises(prompt_orchestrator.PreconditionError):
        prompt_orchestrator.generate(
            conn, session_id=session_id,
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )


def test_generate_includes_reference_summaries_in_composition(
    conn, session_id, monkeypatch,
):
    ref = source_image_repo.insert(
        conn, session_id=session_id, path=f"images/{session_id}/sources/ref.png",
        original_filename="ref-pose.png", is_main=False,
    )
    source_image_repo.set_analysis(
        conn, ref["id"], analysis="dynamic action pose", refining_prompt=None,
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: dict = {"calls": []}

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured["calls"].append(messages)
        if len(captured["calls"]) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured["calls"][1][0]["content"]
    assert "Image_2" in composition_system
    assert "dynamic action pose" in composition_system


def test_generate_raises_for_unknown_session(conn):
    with pytest.raises(prompt_orchestrator.PreconditionError):
        prompt_orchestrator.generate(
            conn, session_id="nope",
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )


def test_generate_excludes_hidden_loras_when_show_hidden_off(
    conn, session_id, monkeypatch,
):
    """When the global ``show_hidden`` setting is off, both retrieved and
    pinned hidden LoRAs must be dropped from the composition prompt — the
    prompt LLM should never see them as available."""
    from app.services import indexer
    library_repo.create_lora(
        conn, name="hidden-retrieved", display_name="hidden-retrieved",
        description="d", tags=[], trigger_words=[], family_id="sdxl",
    )
    library_repo.create_lora(
        conn, name="hidden-pinned", display_name="hidden-pinned",
        description="d", tags=[], trigger_words=[], family_id="sdxl",
    )
    indexer.upsert_lora_vector(conn, lora_name="hidden-retrieved", vector=[0.001] * 1024)
    indexer.upsert_lora_vector(conn, lora_name="hidden-pinned", vector=[0.001] * 1024)
    indexer.upsert_lora_vector(conn, lora_name="lora-a", vector=[0.001] * 1024)
    library_repo.set_lora_hidden(conn, "hidden-retrieved", hidden=True)
    library_repo.set_lora_hidden(conn, "hidden-pinned", hidden=True)
    session_repo.set_pinned_loras(
        conn, session_id, [{"lora_name": "hidden-pinned", "weight_override": 0.7}],
    )
    settings_repo.set_privacy(conn, show_hidden=False)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: dict = {"calls": []}

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured["calls"].append(messages)
        if len(captured["calls"]) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured["calls"][1][0]["content"]
    assert "hidden-retrieved" not in composition_system
    assert "hidden-pinned" not in composition_system
    assert "lora-a" in composition_system


def test_generate_includes_hidden_loras_when_show_hidden_on(
    conn, session_id, monkeypatch,
):
    """Mirror of the previous test: when ``show_hidden`` is on, hidden
    LoRAs are surfaced to the prompt LLM as usual."""
    from app.services import indexer
    library_repo.create_lora(
        conn, name="hidden-retrieved", display_name="hidden-retrieved",
        description="d", tags=[], trigger_words=[], family_id="sdxl",
    )
    indexer.upsert_lora_vector(conn, lora_name="hidden-retrieved", vector=[0.001] * 1024)
    indexer.upsert_lora_vector(conn, lora_name="lora-a", vector=[0.001] * 1024)
    library_repo.set_lora_hidden(conn, "hidden-retrieved", hidden=True)
    settings_repo.set_privacy(conn, show_hidden=True)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: dict = {"calls": []}

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured["calls"].append(messages)
        if len(captured["calls"]) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured["calls"][1][0]["content"]
    assert "hidden-retrieved" in composition_system


def test_generate_persists_pinned_loras_into_candidates(conn, session_id, monkeypatch):
    library_repo.create_lora(
        conn, name="pinned-x", display_name="pinned-x",
        description="pinned desc", tags=[], trigger_words=[], family_id="sdxl",
    )
    session_repo.set_pinned_loras(
        conn, session_id, [{"lora_name": "pinned-x", "weight_override": 0.9}],
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured.setdefault("calls", []).append(messages)
        if len(captured["calls"]) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured["calls"][1][0]["content"]
    assert "pinned-x" in composition_system


def test_generate_does_not_pass_response_format(conn, session_id, monkeypatch):
    """LMStudio (qwen3.6 builds) reject response_format=json_object. The
    orchestrator must NOT pass response_format — the prompt instruction +
    _extract_json_object fallback are sufficient. Smoke-tested 2026-04-26."""
    import json
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: list = []
    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured.append(response_format)
        if len(captured) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert captured == [None, None], (
        "response_format must remain unset until LMStudio json_schema support is wired"
    )


def test_generate_rejects_t2i_session_with_precondition_error(conn, session_id):
    conn.execute(
        "UPDATE sessions SET session_type = 't2i' WHERE id = ?", (session_id,),
    )
    with pytest.raises(prompt_orchestrator.PreconditionError) as exc:
        prompt_orchestrator.generate(
            conn, session_id=session_id,
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
    assert "t2i" in str(exc.value)


def test_generate_appends_family_prompt_i2i_to_composition_system(
    conn, session_id, monkeypatch,
):
    conn.execute(
        "UPDATE families SET prompt_i2i = ? WHERE id = 'sdxl'",
        ("APPEND_I2I_GUIDE_MARKER",),
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: dict = {"calls": []}

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured["calls"].append(messages)
        if len(captured["calls"]) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured["calls"][1][0]["content"]
    assert "APPEND_I2I_GUIDE_MARKER" in composition_system
    assert "# Mode: i2i" in composition_system
