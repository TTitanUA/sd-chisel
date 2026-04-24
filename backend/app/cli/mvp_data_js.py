"""Parse a subset of JavaScript for `mvp-ui-mock/app/data.js` library blocks.

The mock file is not JSON (single-quoted strings, optional trailing commas). We
parse the `FAMILIES` / `MODELS` / `LORAS` const arrays with a small lexer that
ignores string contents when scanning brackets.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class MvpDataParseError(ValueError):
    pass


def _strip_line_comments(text: str) -> str:
    out_lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _skip_js_string(s: str, i: int, quote: str) -> int:
    """Return index after the closing quote; supports \\ escapes within strings."""
    if i >= len(s) or s[i] != quote:
        raise MvpDataParseError("expected opening quote for string")
    i += 1
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    raise MvpDataParseError("unterminated string literal")


def _find_matching_bracket(s: str, start: int, open_c: str, close_c: str) -> int:
    """Index of the matching `close_c` for `s[start] == open_c`, respecting strings."""
    if start >= len(s) or s[start] != open_c:
        raise MvpDataParseError(f"expected '{open_c}' at {start}")
    depth = 0
    i = start
    while i < len(s):
        c = s[i]
        if c in ("'", '"'):
            i = _skip_js_string(s, i, c)
            continue
        if c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise MvpDataParseError(f"unclosed bracket starting at {start}")


def _extract_top_level_const_array(text: str, const_name: str) -> str:
    marker = f"const {const_name} ="
    pos = text.find(marker)
    if pos < 0:
        raise MvpDataParseError(f"{marker!r} not found in data.js")
    pos += len(marker)
    while pos < len(text) and text[pos] in " \t\n\r":
        pos += 1
    end = _find_matching_bracket(text, pos, "[", "]")
    return text[pos : end + 1]


def _parse_js_string(s: str, i: int) -> tuple[str, int]:
    if i >= len(s) or s[i] not in ("'", '"'):
        raise MvpDataParseError("string expected")
    quote = s[i]
    i += 1
    out: list[str] = []
    while i < len(s):
        c = s[i]
        if c == "\\":
            if i + 1 >= len(s):
                raise MvpDataParseError("bad escape")
            nxt = s[i + 1]
            if nxt in (quote, "\\"):
                out.append(nxt)
            else:
                out.append(nxt)  # keep backslash for unknown escapes (mock has none)
            i += 2
            continue
        if c == quote:
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise MvpDataParseError("unterminated string")


class _Parser:
    def __init__(self, s: str):
        self.s = s
        self.i = 0

    def _peek(self) -> str:
        if self.i >= len(self.s):
            return ""
        return self.s[self.i]

    def _skip_ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\n\r":
            self.i += 1

    def parse_value(self) -> Any:
        self._skip_ws()
        c = self._peek()
        if c == "[":
            return self.parse_array()
        if c == "{":
            return self.parse_object()
        if c in ("'", '"'):
            s, j = _parse_js_string(self.s, self.i)
            self.i = j
            return s
        if c == "-" or c.isdigit() or c == ".":
            return self.parse_number()
        if self.s[self.i : self.i + 4] == "true" and (self._end_of_token(self.i + 4)):
            self.i += 4
            return True
        if self.s[self.i : self.i + 5] == "false" and (self._end_of_token(self.i + 5)):
            self.i += 5
            return False
        if self.s[self.i : self.i + 4] == "null" and (self._end_of_token(self.i + 4)):
            self.i += 4
            return None
        raise MvpDataParseError(f"unexpected token at {self.i}: {self.s[self.i : self.i + 20]!r}")

    def _end_of_token(self, j: int) -> bool:
        if j >= len(self.s):
            return True
        n = self.s[j]
        return n in " \t\n\r,]}"

    def parse_number(self) -> float:
        self._skip_ws()
        m = re.match(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", self.s[self.i :])
        if not m:
            raise MvpDataParseError("number expected")
        self.i += len(m.group(0))
        return float(m.group(0)) if ("." in m.group(0) or "e" in m.group(0).lower()) else int(m.group(0))

    def parse_object(self) -> dict[str, Any]:
        self._skip_ws()
        if self._peek() != "{":
            raise MvpDataParseError("{ expected")
        self.i += 1
        d: dict[str, Any] = {}
        self._skip_ws()
        if self._peek() == "}":
            self.i += 1
            return d
        while True:
            self._skip_ws()
            c = self._peek()
            if c in ("'", '"'):
                key, self.i = _parse_js_string(self.s, self.i)
            elif re.match(r"[a-zA-Z_$][\w$]*", self.s[self.i :]) is not None:
                m = re.match(r"[a-zA-Z_$][\w$]*", self.s[self.i :])
                assert m is not None
                key = m.group(0)
                self.i += len(key)
            else:
                raise MvpDataParseError(f"bad object key at {self.i}")
            self._skip_ws()
            if self._peek() != ":":
                raise MvpDataParseError("':' expected after object key")
            self.i += 1
            val = self.parse_value()
            d[key] = val
            self._skip_ws()
            if self._peek() == "}":
                self.i += 1
                return d
            if self._peek() != ",":
                raise MvpDataParseError("',' or '}' expected in object")
            self.i += 1
            # trailing comma: ,}
            self._skip_ws()
            if self._peek() == "}":
                self.i += 1
                return d

    def parse_array(self) -> list[Any]:
        self._skip_ws()
        if self._peek() != "[":
            raise MvpDataParseError("[ expected")
        self.i += 1
        out: list[Any] = []
        self._skip_ws()
        if self._peek() == "]":
            self.i += 1
            return out
        while True:
            out.append(self.parse_value())
            self._skip_ws()
            if self._peek() == "]":
                self.i += 1
                return out
            if self._peek() != ",":
                raise MvpDataParseError("',' or ']' expected in array")
            self.i += 1
            # trailing comma before ]
            self._skip_ws()
            if self._peek() == "]":
                self.i += 1
                return out


def parse_js_value(text: str) -> Any:
    p = _Parser(text.strip())
    v = p.parse_value()
    p._skip_ws()
    if p.i != len(p.s):
        raise MvpDataParseError(f"trailing data after value at {p.i}")
    return v


def load_mvp_library_data(data_js: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not data_js.is_file():
        raise FileNotFoundError(f"data.js not found: {data_js}")
    raw = _strip_line_comments(data_js.read_text(encoding="utf-8"))
    arr_f = _extract_top_level_const_array(raw, "FAMILIES")
    arr_m = _extract_top_level_const_array(raw, "MODELS")
    arr_l = _extract_top_level_const_array(raw, "LORAS")

    f = parse_js_value(arr_f)
    m = parse_js_value(arr_m)
    loras_arr = parse_js_value(arr_l)
    if not isinstance(f, list) or not isinstance(m, list) or not isinstance(loras_arr, list):
        raise MvpDataParseError("FAMILIES/MODELS/LORAS must be arrays")
    for name, block in (("FAMILIES", f), ("MODELS", m), ("LORAS", loras_arr)):
        for i, el in enumerate(block):
            if not isinstance(el, dict):
                raise MvpDataParseError(f"{name}[{i}] is not an object")
    return (f, m, loras_arr)  # type: ignore[return-value]
