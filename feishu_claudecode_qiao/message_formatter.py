"""Message formatting utilities for Feishu (Lark) bot integration.

Converts plain markdown text into Feishu-compatible interactive card JSON
or plain-text payloads, with automatic sentiment-based styling.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Sentiment / colour detection
# ---------------------------------------------------------------------------

_SENTIMENT_PATTERNS: dict[str, list[str]] = {
    "red": ["错误", "失败", "严重", "重大隐患"],
    "orange": ["警告", "隐患"],
    "green": ["成功", "完成", "通过"],
}


def _detect_header_color(text: str) -> str:
    """Return a Feishu card header colour based on keyword sentiment.

    Priority follows the order: red > orange > green > blue (default).
    """
    for color, keywords in _SENTIMENT_PATTERNS.items():
        for kw in keywords:
            if kw in text:
                return color
    return "blue"


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^#\s+(.*)$", re.MULTILINE)


def _extract_title(text: str) -> str:
    """Extract the title only if there is exactly one level-1 heading (the summary title)."""
    matches = _TITLE_RE.findall(text)
    if len(matches) == 1:
        return matches[0].strip()
    return ""


# ---------------------------------------------------------------------------
# Markdown feature detection
# ---------------------------------------------------------------------------

_MARKDOWN_INDICATORS: tuple[str, ...] = (
    "**", "__",  # bold
    "*", "_",    # italic / emphasis (careful – also bullets)
    "```",       # code block
    "`",         # inline code
    "#",         # heading
    "|",         # table pipe
    "- ",        # unordered list
    "* ",        # unordered list
    "1. ",       # ordered list
    "[",         # link
    "> ",        # blockquote
)


def _has_markdown_formatting(text: str) -> bool:
    """Return ``True`` if *text* contains recognisable markdown syntax."""
    stripped = text.strip()
    for indicator in _MARKDOWN_INDICATORS:
        if indicator in stripped:
            return True
    # Heading pattern
    if re.search(r"^#{1,6}\s", stripped, re.MULTILINE):
        return True
    # Table pattern (at least one row with pipes)
    if re.search(r"\|.*\|", stripped):
        return True
    # Code fence
    if re.search(r"```[\s\S]*?```", stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Markdown parsing into segments
# ---------------------------------------------------------------------------

def _parse_segments(text: str) -> list[dict[str, Any]]:
    """Split markdown text into segments: text, table, code_block."""
    segments: list[dict[str, Any]] = []
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            segments.append({
                "type": "code_block",
                "lang": lang,
                "content": "\n".join(code_lines),
            })
            continue

        # Table
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            segments.append({
                "type": "table",
                "lines": table_lines,
            })
            continue

        # Horizontal rule – skip
        if stripped in ("---", "***", "___"):
            i += 1
            continue

        # Regular text
        text_lines: list[str] = []
        while i < len(lines):
            s = lines[i].strip()
            if s.startswith("```") or (s.startswith("|") and "|" in s[1:]):
                break
            text_lines.append(lines[i])
            i += 1

        if text_lines:
            content = "\n".join(text_lines).strip()
            if content:
                segments.append({
                    "type": "text",
                    "content": content,
                })

    return segments


# ---------------------------------------------------------------------------
# Segment-to-card-element converters
# ---------------------------------------------------------------------------

def _table_to_column_set(lines: list[str]) -> dict[str, Any]:
    """Convert markdown table lines into a Feishu column_set element."""
    rows: list[list[str]] = []
    for line in lines:
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        cells = [c.strip() for c in s.split("|")]
        rows.append(cells)

    # Filter separator rows like |---|---|
    data_rows: list[list[str]] = []
    for row in rows:
        if all(re.match(r"^[:|\-\s]+$", c) for c in row):
            continue
        data_rows.append(row)

    if not data_rows:
        return {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}

    num_cols = max(len(r) for r in data_rows)

    columns: list[dict[str, Any]] = []
    for col_idx in range(num_cols):
        col_parts: list[str] = []
        for row_idx, row in enumerate(data_rows):
            cell = row[col_idx] if col_idx < len(row) else ""
            if row_idx == 0:
                col_parts.append(f"**{cell}**")
            else:
                col_parts.append(cell)

        columns.append({
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n\n".join(col_parts)},
            }],
        })

    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "columns": columns,
    }


def _code_to_element(lang: str, content: str) -> dict[str, Any]:
    """Convert a code block into a card element.

    lark_md does not support fenced code blocks, so we render as plain
    monospaced text inside a div.
    """
    display = f"```{lang}\n{content}\n```" if lang else f"```\n{content}\n```"
    return {"tag": "div", "text": {"tag": "lark_md", "content": display}}


def _text_to_element(content: str) -> dict[str, Any]:
    """Convert a plain text segment into a lark_md div element."""
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def markdown_to_card(text: str) -> str:
    """Convert markdown text into a Feishu interactive card JSON string.

    Features:

    * Auto-detects header colour based on sentiment keywords.
    * Extracts the title when there is exactly one level-1 heading.
    * Converts markdown tables into Feishu ``column_set`` elements.
    * Converts code blocks into plain-text card elements.
    * Promotes ##+ sub-headings to bold text (lark_md does not support
      heading syntax in card bodies).
    """
    title = _extract_title(text)
    header_color = _detect_header_color(text)

    # Remove the single level-1 heading from body content to avoid duplication
    content = text
    if title:
        content = _TITLE_RE.sub("", content, count=1).strip()

    # lark_md does not support ##+ headings – convert to bold
    content = re.sub(r"^#{2,6}\s+(.*)$", r"**\1**", content, flags=re.MULTILINE)

    # Parse into segments and convert each to a card element
    segments = _parse_segments(content)
    elements: list[dict[str, Any]] = []

    for seg in segments:
        if seg["type"] == "table":
            elements.append(_table_to_column_set(seg["lines"]))
        elif seg["type"] == "code_block":
            elements.append(_code_to_element(seg["lang"], seg["content"]))
        elif seg["type"] == "text":
            seg_text = seg["content"].strip()
            if seg_text:
                elements.append(_text_to_element(seg_text))

    if not elements:
        elements = [_text_to_element(content or "（无内容）")]

    card: dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "elements": elements,
    }
    if title:
        card["header"] = {
            "template": header_color,
            "title": {
                "tag": "plain_text",
                "content": title,
            },
        }

    return json.dumps(card, ensure_ascii=False, separators=(",", ":"))


def auto_detect_format(text: str) -> tuple[str, str]:
    """Automatically choose the best Feishu message format for *text*.

    If the text contains markdown formatting (headings, bold, lists,
    code blocks, tables, etc.) it is wrapped as an interactive card.
    Otherwise it is returned as plain text.

    Args:
        text: The message content to format.

    Returns:
        A tuple ``(content_str, msg_type)`` where *msg_type* is either
        ``"interactive"`` (card) or ``"text"`` (plain text).
    """
    if _has_markdown_formatting(text):
        return markdown_to_card(text), "interactive"

    # Plain text payload – Feishu expects a JSON string with a "text" field.
    payload = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":"))
    return payload, "text"
