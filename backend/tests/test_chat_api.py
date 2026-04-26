import pytest
from pydantic import ValidationError

from app.models.chat import ChatRequest, MessageOut


def test_chat_request_strips_and_rejects_empty():
    assert ChatRequest(content="  hi  ").content == "hi"
    with pytest.raises(ValidationError):
        ChatRequest(content="   ")
    with pytest.raises(ValidationError):
        ChatRequest(content="")


def test_chat_request_rejects_oversize():
    with pytest.raises(ValidationError):
        ChatRequest(content="x" * 8001)


def test_message_out_round_trip():
    m = MessageOut(id=1, session_id="s", role="user", content="hi", created_at=10)
    assert m.model_dump() == {
        "id": 1, "session_id": "s", "role": "user", "content": "hi", "created_at": 10,
    }
