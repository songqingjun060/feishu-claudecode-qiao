from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .session_store import SessionMeta


@dataclass(frozen=True)
class SessionDecision:
    strategy: str
    session_id: str | None
    remember_turn: bool = True
    force_rollover: bool = False
    reason: str = ""


LIGHT_TEXT_MAX_CHARS = 120
HEAVY_INPUT_CHARS = 20_000
HEAVY_MESSAGE_COUNT = 12

_WORK_PATTERNS = (
    r"[A-Za-z]:[\\/]",
    r"\.(xlsx|xls|csv|pdf|docx|doc|pptx|zip|7z|rar|png|jpg|jpeg|mp4)\b",
    r"\b(BI|物流码|Excel|表格|文件|图片|语音|PDF|压缩包|上传|生成|分析|查询)\b",
    r"\b(read|write|edit|analyze|upload|download|query|excel|file)\b",
)

_FRESH_PREFIXES = ("/new", "/fresh", "/reset session")


def choose_session_strategy(
    content: str,
    *,
    msg_type: str,
    session_meta: SessionMeta | None,
    effective_rule: dict[str, Any],
) -> SessionDecision:
    policy = (effective_rule or {}).get("session_strategy", {}) or {}
    mode = str(policy.get("mode", "auto")).lower()
    saved_session_id = (session_meta.session_id if session_meta else "") or ""

    if mode in {"light", "work", "fresh", "stateless"}:
        return _decision_for_mode(mode, saved_session_id)

    stripped = content.strip()
    if any(stripped.lower().startswith(prefix) for prefix in _FRESH_PREFIXES):
        return SessionDecision("fresh", None, remember_turn=True, reason="explicit_fresh")

    if msg_type != "text":
        return SessionDecision("work", saved_session_id or None, reason="media_message")

    if _looks_like_work(stripped):
        return SessionDecision("work", saved_session_id or None, reason="work_intent")

    if _is_heavy(session_meta) and len(stripped) <= int(policy.get("light_text_max_chars", LIGHT_TEXT_MAX_CHARS)):
        return SessionDecision("light", None, remember_turn=False, reason="heavy_session_short_text")

    return SessionDecision("work", saved_session_id or None, reason="default_work")


def should_force_rollover_after_timing(
    *,
    prompt_built_to_claude_completed_ms: int,
    threshold_ms: int = 30_000,
) -> bool:
    return prompt_built_to_claude_completed_ms >= threshold_ms


def _decision_for_mode(mode: str, saved_session_id: str) -> SessionDecision:
    if mode == "light":
        return SessionDecision("light", None, remember_turn=False, reason="rule_light")
    if mode == "fresh":
        return SessionDecision("fresh", None, remember_turn=True, reason="rule_fresh")
    if mode == "stateless":
        return SessionDecision("stateless", None, remember_turn=False, reason="rule_stateless")
    return SessionDecision("work", saved_session_id or None, remember_turn=True, reason="rule_work")


def _is_heavy(meta: SessionMeta | None) -> bool:
    if meta is None:
        return False
    return meta.input_chars >= HEAVY_INPUT_CHARS or meta.message_count >= HEAVY_MESSAGE_COUNT


def _looks_like_work(content: str) -> bool:
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in _WORK_PATTERNS)
