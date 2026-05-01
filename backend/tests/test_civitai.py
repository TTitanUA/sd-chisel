from __future__ import annotations

import json

import httpx
import pytest

from app.services import civitai


# ---------------------------------------------------------------------------
# parse_civitai_ref
# ---------------------------------------------------------------------------


def test_parse_air_with_version():
    assert civitai.parse_civitai_ref("urn:air:flux1:lora:civitai:12345@67890") == (12345, 67890)


def test_parse_air_with_file_segment():
    # AIR may include +fileId / .format suffixes — we ignore those.
    air = "urn:air:sdxl:checkpoint:civitai:827184@2514310+2402203"
    assert civitai.parse_civitai_ref(air) == (827184, 2514310)


def test_parse_air_short_form():
    # Both `urn:` and `air:` are optional.
    assert civitai.parse_civitai_ref("air:flux1:lora:civitai:111@222") == (111, 222)
    assert civitai.parse_civitai_ref("flux1:lora:civitai:111@222") == (111, 222)
    assert civitai.parse_civitai_ref("civitai:111@222") == (111, 222)


def test_parse_air_without_version():
    assert civitai.parse_civitai_ref("urn:air:sdxl:lora:civitai:42") == (42, None)


def test_parse_url_with_query():
    url = "https://civitai.com/models/12345?modelVersionId=67890"
    assert civitai.parse_civitai_ref(url) == (12345, 67890)


def test_parse_url_with_slug_and_query():
    url = "https://civitai.com/models/12345/some-name?modelVersionId=67890"
    assert civitai.parse_civitai_ref(url) == (12345, 67890)


def test_parse_url_without_version():
    assert civitai.parse_civitai_ref("https://civitai.com/models/12345") == (12345, None)


def test_parse_bare_integer():
    assert civitai.parse_civitai_ref("12345") == (12345, None)


def test_parse_invalid_raises():
    with pytest.raises(civitai.CivitaiError):
        civitai.parse_civitai_ref("not-a-civitai-ref")
    with pytest.raises(civitai.CivitaiError):
        civitai.parse_civitai_ref("")


# ---------------------------------------------------------------------------
# html_to_markdown
# ---------------------------------------------------------------------------


def test_html_strips_tags_and_paragraphs():
    out = civitai.html_to_markdown("<p>Hello <strong>world</strong>.</p><p>Second.</p>")
    assert out == "Hello **world**.\n\nSecond."


def test_html_preserves_lists():
    html = "<ul><li>One</li><li>Two</li></ul>"
    out = civitai.html_to_markdown(html)
    assert "- One" in out
    assert "- Two" in out


def test_html_ordered_list_numbered():
    html = "<ol><li>First</li><li>Second</li></ol>"
    out = civitai.html_to_markdown(html)
    assert "1. First" in out
    assert "2. Second" in out


def test_html_links():
    html = '<p>See <a href="https://example.com">here</a>.</p>'
    out = civitai.html_to_markdown(html)
    assert out == "See [here](https://example.com)."


def test_html_drops_anchors_without_href():
    out = civitai.html_to_markdown("<p>plain <a>text</a> here</p>")
    assert out == "plain text here"


def test_html_skips_script_and_style():
    out = civitai.html_to_markdown(
        "<p>before</p><script>alert('x')</script><style>p{color:red}</style><p>after</p>"
    )
    assert "alert" not in out
    assert "color:red" not in out
    assert "before" in out
    assert "after" in out


def test_html_empty_input():
    assert civitai.html_to_markdown("") == ""
    assert civitai.html_to_markdown(None) == ""


def test_html_headings():
    out = civitai.html_to_markdown("<h2>Title</h2><p>body</p>")
    assert out.startswith("## Title")


# ---------------------------------------------------------------------------
# fetch_lora_metadata (with MockTransport)
# ---------------------------------------------------------------------------


def _model_payload() -> dict:
    return {
        "id": 100,
        "name": "MyLoRA",
        "description": "<p>A <strong>great</strong> LoRA.</p>",
        "type": "LORA",
        "tags": ["style", "anime"],
        "creator": {"username": "alice"},
        "modelVersions": [
            {
                "id": 200,
                "name": "v1.0",
                "baseModel": "Flux.1 D",
                "trainedWords": ["mylora_token", "magic"],
                "air": "urn:air:flux1:lora:civitai:100@200",
                "files": [
                    {"primary": True, "name": "my_lora.safetensors"},
                ],
            },
            {
                "id": 199,
                "name": "v0.9",
                "baseModel": "Flux.1 D",
                "trainedWords": [],
                "files": [{"primary": True, "name": "my_lora_old.safetensors"}],
            },
        ],
    }


@pytest.fixture
def mock_civitai(monkeypatch):
    def _install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(civitai, "_TRANSPORT", transport)
    return _install


def test_fetch_picks_specified_version(mock_civitai):
    payload = _model_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/models/100"
        return httpx.Response(200, json=payload)

    mock_civitai(handler)
    result = civitai.fetch_lora_metadata(100, 199)
    assert result["display_name"] == "MyLoRA"
    assert result["version"] == "v0.9"
    assert result["name"] == "my_lora_old"  # extension stripped
    assert result["source_url"] == "https://civitai.com/models/100?modelVersionId=199"


def test_fetch_picks_latest_when_version_omitted(mock_civitai):
    mock_civitai(lambda req: httpx.Response(200, json=_model_payload()))
    result = civitai.fetch_lora_metadata(100, None)
    assert result["version"] == "v1.0"
    assert result["trigger_words"] == ["mylora_token", "magic"]
    assert result["air"] == "urn:air:flux1:lora:civitai:100@200"


def test_fetch_full_mapping(mock_civitai):
    mock_civitai(lambda req: httpx.Response(200, json=_model_payload()))
    result = civitai.fetch_lora_metadata(100, 200)
    assert result == {
        "name": "my_lora",
        "display_name": "MyLoRA",
        "description": "A **great** LoRA.",
        "tags": ["style", "anime"],
        "trigger_words": ["mylora_token", "magic"],
        "recommended_weight": None,
        "author": "alice",
        "version": "v1.0",
        "source_url": "https://civitai.com/models/100?modelVersionId=200",
        "base_model": "Flux.1 D",
        "model_type": "LORA",
        "air": "urn:air:flux1:lora:civitai:100@200",
    }


def test_fetch_falls_back_to_version_endpoint_when_not_in_model(mock_civitai):
    """If the requested version isn't listed under the model (e.g. unpublished),
    the service falls back to GET /model-versions/{id}."""
    payload = _model_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models/100":
            return httpx.Response(200, json=payload)
        if request.url.path == "/api/v1/model-versions/999":
            return httpx.Response(200, json={
                "id": 999,
                "name": "v2.0-beta",
                "baseModel": "Flux.1 D",
                "trainedWords": ["beta"],
                "files": [{"primary": True, "name": "beta.safetensors"}],
            })
        raise AssertionError(f"unexpected url {request.url}")

    mock_civitai(handler)
    result = civitai.fetch_lora_metadata(100, 999)
    assert result["version"] == "v2.0-beta"
    assert result["trigger_words"] == ["beta"]


def test_fetch_404_raises(mock_civitai):
    mock_civitai(lambda req: httpx.Response(404, json={"error": "not found"}))
    with pytest.raises(civitai.CivitaiError, match="not found"):
        civitai.fetch_lora_metadata(404404, None)
