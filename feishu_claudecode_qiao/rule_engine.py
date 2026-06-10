from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


VALID_SESSION_MODES = {"shared_chat", "per_user", "stateless"}
VALID_PERMISSION_PROFILES = {"readonly", "safe", "dev", "admin", "stateless"}

DEFAULT_RULE = {
    "workspace": "",
    "allowed_paths": [],
    "permission_profile": "safe",
    "session_mode": "shared_chat",
    "custom_prompt": "",
    "members": {},
    "rule_admins": [],
    "confirm_policy": {
        "delete": "confirm",
        "move": "confirm",
        "overwrite": "confirm",
        "read_sensitive": "confirm",
        "shell": "confirm",
    },
    "context_policy": {
        "mode": "auto_rollover",
        "score_threshold": 100,
        "soft_message_limit": 20,
        "hard_message_limit": 35,
        "ttl_hours": 72,
        "min_messages_between_rollovers": 8,
        "rollover_cooldown_hours": 2,
        "carry_summary": True,
    },
    "memory_policy": {
        "enabled": True,
        "rolling_summary_max_chars": 6000,
        "history_max_items": 50,
        "history_item_max_chars": 4000,
        "inject_max_chars": 4000,
    },
    "output_policy": {
        "verbosity": "normal",
        "long_reply_mode": "summary_then_file",
        "max_inline_chars": 3000,
    },
    "media": {
        "image": "claude_image_path",
        "audio": "whisper_to_text",
        "file": "path_to_claude",
    },
}


@dataclass(frozen=True)
class EffectiveRule:
    data: dict[str, Any]
    source: list[str] = field(default_factory=list)
    member_id: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def resolve_rule(chat_rule: dict[str, Any], sender_id: str = "", temporary: dict[str, Any] | None = None) -> EffectiveRule:
    source = ["default"]
    merged = deep_merge(DEFAULT_RULE, chat_rule or {})
    source.append("chat")

    members = merged.get("members", {})
    if sender_id and sender_id in members:
        merged = deep_merge(merged, members[sender_id])
        source.append(f"member:{sender_id}")

    if temporary:
        merged = deep_merge(merged, temporary)
        source.append("temporary")

    return EffectiveRule(data=merged, source=source, member_id=sender_id)


def validate_rule(rule: dict[str, Any]) -> list[str]:
    errors = []
    session_mode = rule.get("session_mode", "")
    if session_mode and session_mode not in VALID_SESSION_MODES:
        errors.append(f"invalid session_mode: {session_mode}")
    permission_profile = rule.get("permission_profile", "")
    if permission_profile and permission_profile not in VALID_PERMISSION_PROFILES:
        errors.append(f"invalid permission_profile: {permission_profile}")
    return errors


def build_session_key(chat_id: str, sender_id: str, session_mode: str) -> str | None:
    if session_mode == "shared_chat":
        return f"chat:{chat_id}"
    elif session_mode == "per_user":
        return f"chat:{chat_id}:user:{sender_id}"
    elif session_mode == "stateless":
        return None
    return f"chat:{chat_id}"


def permission_mode_for_profile(profile: str, fallback: str = "default") -> str:
    mapping = {
        "readonly": "default",
        "safe": "default",
        "dev": "acceptEdits",
        "admin": "bypassPermissions",
        "stateless": "default",
    }
    return mapping.get(profile or "", fallback)
