from __future__ import annotations

from app.services import prompt_builder


def _lora(name: str, **over) -> dict:
    base = {
        "name": name,
        "display_name": name,
        "description": f"# {name}\nhelpful description",
        "tags": ["lighting"],
        "trigger_words": [f"{name}_trigger"],
        "recommended_weight": 0.7,
        "family_id": "sdxl",
    }
    base.update(over)
    return base


def test_build_intent_messages_includes_summary_history_and_tags():
    msgs = prompt_builder.build_intent_messages(
        vl_summary="anime girl moody lighting",
        chat_messages=[
            {"role": "user", "content": "make it darker"},
            {"role": "assistant", "content": "ok"},
        ],
        distinct_tags=["lighting", "style"],
    )
    assert msgs[0]["role"] == "system"
    user = next(m for m in msgs if m["role"] == "user")
    assert "anime girl moody lighting" in user["content"]
    assert "make it darker" in user["content"]
    assert "lighting" in user["content"] and "style" in user["content"]
    # Schema instruction is in the system message
    assert '"intents"' in msgs[0]["content"]


def test_build_intent_messages_handles_empty_tags_explicitly():
    msgs = prompt_builder.build_intent_messages(
        vl_summary="x", chat_messages=[], distinct_tags=[],
    )
    user = next(m for m in msgs if m["role"] == "user")
    # Cold-start phrasing — must be obvious to the LLM that tags don't exist yet
    lower = user["content"].lower()
    assert "no tags" in lower or "cold" in lower or "we have no" in lower


def test_build_composition_messages_lists_loras_with_separator():
    msgs = prompt_builder.build_composition_messages(
        family_prompt_guide="GUIDE TEXT",
        model_description="MODEL DELTA",
        candidates=[_lora("a"), _lora("b")],
        vl_summary="VLS",
        chat_messages=[{"role": "user", "content": "go"}],
        use_negative=True,
    )
    sys = msgs[0]["content"]
    assert "GUIDE TEXT" in sys
    assert "MODEL DELTA" in sys
    assert "# Available LoRAs" in sys
    assert "\n---\n" in sys
    assert "# a" in sys and "# b" in sys
    assert "VLS" in sys


def test_build_composition_messages_omits_model_description_when_none():
    msgs = prompt_builder.build_composition_messages(
        family_prompt_guide="GUIDE",
        model_description=None,
        candidates=[],
        vl_summary="V",
        chat_messages=[],
        use_negative=False,
    )
    sys = msgs[0]["content"]
    assert "GUIDE" in sys
    # Should not produce a stray empty section
    assert "MODEL DELTA" not in sys


def test_build_intent_messages_includes_reference_summaries():
    msgs = prompt_builder.build_intent_messages(
        vl_summary="main analysis",
        chat_messages=[],
        distinct_tags=[],
        reference_summaries=[("ref-a.png", "warm palette"), ("ref-b.jpg", "tight crop")],
    )
    user = next(m for m in msgs if m["role"] == "user")
    assert "main analysis" in user["content"]
    assert "# Reference images" in user["content"]
    assert "ref-a.png: warm palette" in user["content"]
    assert "ref-b.jpg: tight crop" in user["content"]


def test_build_composition_messages_includes_reference_summaries():
    msgs = prompt_builder.build_composition_messages(
        family_prompt_guide="GUIDE", model_description=None, candidates=[],
        vl_summary="MAIN", chat_messages=[], use_negative=False,
        reference_summaries=[("r.png", "blue tones")],
    )
    sys = msgs[0]["content"]
    assert "MAIN" in sys
    assert "# Reference images" in sys
    assert "r.png: blue tones" in sys


def test_build_composition_messages_use_negative_branch_in_user():
    msgs_on = prompt_builder.build_composition_messages(
        family_prompt_guide="g", model_description=None, candidates=[],
        vl_summary="v", chat_messages=[], use_negative=True,
    )
    msgs_off = prompt_builder.build_composition_messages(
        family_prompt_guide="g", model_description=None, candidates=[],
        vl_summary="v", chat_messages=[], use_negative=False,
    )
    assert "negative" in msgs_on[-1]["content"]
    assert "null" in msgs_off[-1]["content"]
