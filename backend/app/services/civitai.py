"""Civitai metadata import.

Parses Civitai references (AIR / URL / numeric ID), fetches model and
version metadata from the public Civitai API, and converts the HTML
description into a reasonable markdown approximation.

AIR spec: https://developer.civitai.com/site/guide/air
Format: urn:air:{ecosystem}:{type}:{source}:{id}[@{version}][+{file}]
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import httpx

CIVITAI_API = "https://civitai.com/api/v1"

# AIR matches anywhere in the input. Both `urn:` and `air:` prefixes are
# optional per spec; ecosystem/type segments are also optional.
_AIR_RE = re.compile(
    r"(?:urn:)?(?:air:)?"
    r"(?:[\w.-]+:)?(?:[\w.-]+:)?"
    r"civitai:(?P<model>\d+)(?:@(?P<version>\d+))?",
    re.IGNORECASE,
)
_URL_RE = re.compile(
    r"civitai\.com/(?:models|model-versions)/(?P<id>\d+)",
    re.IGNORECASE,
)
_VERSION_QS_RE = re.compile(r"modelVersionId=(\d+)", re.IGNORECASE)


class CivitaiError(Exception):
    pass


def parse_civitai_ref(text: str) -> tuple[int, int | None]:
    """Parse user input into (model_id, version_id | None).

    Accepts:
      - AIR: `urn:air:flux1:lora:civitai:12345@67890`
      - URL: `https://civitai.com/models/12345?modelVersionId=67890`
      - URL: `https://civitai.com/models/12345`
      - URL: `https://civitai.com/model-versions/67890` (treated as version-only)
      - Bare integer (treated as model id)
    """
    text = (text or "").strip()
    if not text:
        raise CivitaiError("empty civitai reference")

    # AIR (most specific — wins over URL match for full URN strings)
    m = _AIR_RE.search(text)
    if m:
        version = m.group("version")
        return int(m.group("model")), int(version) if version else None

    # URL
    m = _URL_RE.search(text)
    if m:
        is_version_url = "/model-versions/" in text.lower()
        ident = int(m.group("id"))
        version_match = _VERSION_QS_RE.search(text)
        if is_version_url:
            return _resolve_version_to_model(ident), ident
        version_id = int(version_match.group(1)) if version_match else None
        return ident, version_id

    # Bare integer
    if text.isdigit():
        return int(text), None

    raise CivitaiError(f"could not parse civitai reference: {text!r}")


def _resolve_version_to_model(version_id: int) -> int:
    """Look up a version's parent model id."""
    data = _http_get(f"{CIVITAI_API}/model-versions/{version_id}")
    model_id = data.get("modelId")
    if not isinstance(model_id, int):
        raise CivitaiError(f"version {version_id} has no modelId")
    return model_id


# ---- HTML to markdown -------------------------------------------------------

_INLINE_OPEN = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}
_HEADING_PREFIX = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}


class _HtmlToMd(HTMLParser):
    """Minimal HTML to markdown converter — handles common Civitai HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.list_kinds: list[str] = []
        self.list_indices: list[int] = []
        self.href_stack: list[str] = []

    def _emit_block_break(self) -> None:
        if not self.parts:
            return
        text = "".join(self.parts).rstrip()
        self.parts = [text, "\n\n"] if text else []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag == "br":
            self.parts.append("  \n")
        elif tag in ("p", "div"):
            self._emit_block_break()
        elif tag in _HEADING_PREFIX:
            self._emit_block_break()
            self.parts.append(_HEADING_PREFIX[tag])
        elif tag in _INLINE_OPEN:
            self.parts.append(_INLINE_OPEN[tag])
        elif tag in ("ul", "ol"):
            self._emit_block_break()
            self.list_kinds.append(tag)
            self.list_indices.append(0)
        elif tag == "li":
            if self.list_kinds:
                self.parts.append("\n" + "  " * (len(self.list_kinds) - 1))
                if self.list_kinds[-1] == "ol":
                    self.list_indices[-1] += 1
                    self.parts.append(f"{self.list_indices[-1]}. ")
                else:
                    self.parts.append("- ")
        elif tag == "a":
            href = (a.get("href") or "").strip()
            self.href_stack.append(href)
            self.parts.append("[")
        elif tag == "img":
            alt = (a.get("alt") or "").strip()
            src = (a.get("src") or "").strip()
            if src:
                self.parts.append(f"![{alt}]({src})")
        elif tag == "blockquote":
            self._emit_block_break()
            self.parts.append("> ")
        elif tag == "hr":
            self._emit_block_break()
            self.parts.append("---\n\n")
        elif tag == "pre":
            self._emit_block_break()
            self.parts.append("```\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return

        if tag in _INLINE_OPEN:
            self.parts.append(_INLINE_OPEN[tag])
        elif tag in ("p", "div"):
            self._emit_block_break()
        elif tag in _HEADING_PREFIX:
            self._emit_block_break()
        elif tag in ("ul", "ol"):
            if self.list_kinds and self.list_kinds[-1] == tag:
                self.list_kinds.pop()
                self.list_indices.pop()
            self._emit_block_break()
        elif tag == "a":
            href = self.href_stack.pop() if self.href_stack else ""
            if href:
                self.parts.append(f"]({href})")
            else:
                # No href — drop the brackets entirely.
                # Find the matching '[' we appended and remove it.
                for i in range(len(self.parts) - 1, -1, -1):
                    if self.parts[i] == "[":
                        del self.parts[i]
                        break
        elif tag == "blockquote":
            self._emit_block_break()
        elif tag == "pre":
            self.parts.append("\n```")
            self._emit_block_break()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(data)

    def get_text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html: str | None) -> str:
    if not html:
        return ""
    parser = _HtmlToMd()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", "", html).strip()
    return parser.get_text()


# ---- Civitai API ------------------------------------------------------------

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Tests can monkeypatch this to inject httpx.MockTransport.
_TRANSPORT: httpx.BaseTransport | None = None


def _http_get(url: str) -> dict[str, Any]:
    try:
        with httpx.Client(
            transport=_TRANSPORT, timeout=_TIMEOUT, follow_redirects=True,
        ) as client:
            res = client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise CivitaiError(f"network error: {exc}") from exc
    if res.status_code == 404:
        raise CivitaiError(f"not found: {url}")
    if res.status_code >= 400:
        raise CivitaiError(f"upstream error {res.status_code}")
    try:
        return res.json()
    except ValueError as exc:
        raise CivitaiError(f"invalid response from civitai: {exc}") from exc


def _strip_extension(name: str) -> str:
    for ext in (".safetensors", ".ckpt", ".pt", ".bin", ".pickletensor"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def fetch_lora_metadata(model_id: int, version_id: int | None) -> dict[str, Any]:
    """Fetch model + version metadata, return a flat dict for import."""
    model = _http_get(f"{CIVITAI_API}/models/{model_id}")

    versions = model.get("modelVersions") or []
    version: dict[str, Any] | None = None
    if version_id is None:
        version = versions[0] if versions else None
    else:
        version = next(
            (v for v in versions if isinstance(v, dict) and v.get("id") == version_id),
            None,
        )
        if version is None:
            # Fall back to the version endpoint directly.
            version = _http_get(f"{CIVITAI_API}/model-versions/{version_id}")

    if version is None:
        raise CivitaiError("model has no versions")

    resolved_version_id = int(version.get("id") or version_id or 0)

    files = version.get("files") or []
    primary = next(
        (f for f in files if isinstance(f, dict) and f.get("primary")),
        files[0] if files else None,
    )
    filename = ""
    if isinstance(primary, dict):
        filename = _strip_extension(str(primary.get("name") or ""))

    raw_tags = model.get("tags") or []
    tags = [str(t) for t in raw_tags if t] if isinstance(raw_tags, list) else []

    raw_words = version.get("trainedWords") or []
    trigger_words = (
        [str(w) for w in raw_words if w] if isinstance(raw_words, list) else []
    )

    creator = model.get("creator") or {}
    author = str(creator.get("username") or "") if isinstance(creator, dict) else ""

    description_html = model.get("description") or ""
    description_md = html_to_markdown(description_html)

    air = str(version.get("air") or "")

    source_url = (
        f"https://civitai.com/models/{model_id}?modelVersionId={resolved_version_id}"
        if resolved_version_id
        else f"https://civitai.com/models/{model_id}"
    )

    return {
        "name": filename,
        "display_name": str(model.get("name") or ""),
        "description": description_md,
        "tags": tags,
        "trigger_words": trigger_words,
        "recommended_weight": None,
        "author": author,
        "version": str(version.get("name") or ""),
        "source_url": source_url,
        "base_model": str(version.get("baseModel") or ""),
        "model_type": str(model.get("type") or ""),
        "air": air,
    }
