"""Per-chat rule configuration management."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_RULE = {
    "workspace": "",
    "allowed_paths": [],
    "require_permission": False,
    "custom_prompt": "",
    "created_at": "",
}


class ChatRules:
    """Manage per-chat rule files under data/rules/{chat_id}.json."""

    def __init__(self, data_dir: str = "data") -> None:
        self._rules_dir = Path(data_dir) / "rules"
        self._rules_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, chat_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", chat_id)
        return self._rules_dir / f"{safe_id}.json"

    def exists(self, chat_id: str) -> bool:
        return self._path(chat_id).exists()

    def get(self, chat_id: str) -> dict[str, Any]:
        path = self._path(chat_id)
        if not path.exists():
            return dict(DEFAULT_RULE)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {**DEFAULT_RULE, **data}
        except (json.JSONDecodeError, TypeError):
            return dict(DEFAULT_RULE)

    def set(self, chat_id: str, **kwargs: Any) -> None:
        path = self._path(chat_id)
        data = self.get(chat_id)
        data.update(kwargs)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, chat_id: str) -> None:
        path = self._path(chat_id)
        if path.exists():
            path.unlink()

    def set_member(self, chat_id: str, sender_id: str, **kwargs: Any) -> None:
        rule = self.get(chat_id)
        members = rule.setdefault("members", {})
        members[sender_id] = {**members.get(sender_id, {}), **kwargs}
        self.set(chat_id, **rule)

    def delete_member(self, chat_id: str, sender_id: str) -> None:
        rule = self.get(chat_id)
        members = rule.get("members", {})
        if sender_id in members:
            del members[sender_id]
            self.set(chat_id, **rule)

    def validate(self, chat_id: str) -> list[str]:
        from .rule_engine import validate_rule
        return validate_rule(self.get(chat_id))

    def is_path_allowed(self, chat_id: str, target_path: str) -> bool:
        """Check if a path is within the allowed workspace for a chat."""
        rule = self.get(chat_id)
        workspace = rule.get("workspace", "")
        allowed = rule.get("allowed_paths", [])

        if not workspace and not allowed:
            return True  # No restrictions

        from pathlib import Path
        try:
            target = Path(target_path).resolve()
        except (OSError, ValueError):
            return False

        allowed_dirs = []
        if workspace:
            allowed_dirs.append(Path(workspace).resolve())
        for p in allowed:
            if p:
                allowed_dirs.append(Path(p).resolve())

        for allowed_dir in allowed_dirs:
            try:
                target.relative_to(allowed_dir)
                return True
            except ValueError:
                continue
        return False
