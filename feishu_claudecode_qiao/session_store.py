from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SessionMeta:
    session_key: str
    session_id: str = ""
    chat_id: str = ""
    sender_id: str = ""
    session_mode: str = "shared_chat"
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0
    input_chars: int = 0
    output_chars: int = 0
    attachment_task_count: int = 0
    last_rollover_at: str = ""
    rollover_count: int = 0
    summary: str = ""
    summary_source_session_id: str = ""
    memory: dict = None
    memory_history: list = None
    status: str = "active"
    force_rollover_next: bool = False

    def __post_init__(self) -> None:
        if self.memory is None:
            self.memory = {
                "rolling_summary": "",
                "updated_at": "",
                "version": 0,
            }
        if self.memory_history is None:
            self.memory_history = []


class SessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, dict] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}
            return

        if not isinstance(raw, dict):
            self._data = {}
            return

        migrated: dict[str, dict] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                migrated[key] = value
            elif isinstance(value, str):
                session_key = key if key.startswith("chat:") else f"chat:{key}"
                meta = SessionMeta(session_key=session_key, session_id=value)
                migrated[session_key] = asdict(meta)
        self._data = migrated

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, session_key: str) -> SessionMeta:
        raw = self._data.get(session_key, {})
        meta = SessionMeta(session_key=session_key)
        for k, v in raw.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        return meta

    def update_session_id(self, session_key: str, session_id: str) -> None:
        meta = self.get(session_key)
        meta.session_id = session_id
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        if not meta.created_at:
            meta.created_at = meta.updated_at
        self._data[session_key] = asdict(meta)
        self.save()

    def record_turn(self, session_key: str, input_chars: int, output_chars: int, attachment_task: bool = False) -> None:
        meta = self.get(session_key)
        meta.message_count += 1
        meta.input_chars += input_chars
        meta.output_chars += output_chars
        if attachment_task:
            meta.attachment_task_count += 1
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        self._data[session_key] = asdict(meta)
        self.save()

    def archive_and_rollover(
        self,
        session_key: str,
        new_summary: str,
        old_session_id: str,
        *,
        rolling_summary: str | None = None,
        history_limit: int = 50,
        history_item_max_chars: int = 4000,
    ) -> SessionMeta:
        meta = self.get(session_key)
        meta.summary = new_summary
        meta.summary_source_session_id = old_session_id
        meta.last_rollover_at = datetime.now(timezone.utc).isoformat()
        meta.rollover_count += 1
        if rolling_summary is not None:
            meta.memory = {
                "rolling_summary": rolling_summary,
                "updated_at": meta.last_rollover_at,
                "version": int((meta.memory or {}).get("version", 0)) + 1,
            }
        if new_summary:
            history_item = {
                "created_at": meta.last_rollover_at,
                "source_session_id": old_session_id,
                "summary": new_summary[: max(0, history_item_max_chars)],
            }
            history = list(meta.memory_history or [])
            history.append(history_item)
            if history_limit > 0:
                history = history[-history_limit:]
            meta.memory_history = history
        meta.session_id = ""
        meta.message_count = 0
        meta.input_chars = 0
        meta.output_chars = 0
        meta.attachment_task_count = 0
        self._data[session_key] = asdict(meta)
        self.save()
        return meta

    def clear_session(self, session_key: str) -> None:
        if session_key in self._data:
            del self._data[session_key]
            self.save()

    def clear_session_id(self, session_key: str) -> None:
        meta = self.get(session_key)
        meta.session_id = ""
        meta.message_count = 0
        meta.input_chars = 0
        meta.output_chars = 0
        meta.attachment_task_count = 0
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        if not meta.created_at:
            meta.created_at = meta.updated_at
        self._data[session_key] = asdict(meta)
        self.save()

    def clear_memory(self, session_key: str) -> None:
        meta = self.get(session_key)
        meta.summary = ""
        meta.summary_source_session_id = ""
        meta.memory = {
            "rolling_summary": "",
            "updated_at": "",
            "version": 0,
        }
        meta.memory_history = []
        self._data[session_key] = asdict(meta)
        self.save()

    def set_force_rollover_next(self, session_key: str, value: bool = True) -> None:
        meta = self.get(session_key)
        meta.force_rollover_next = value
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        self._data[session_key] = asdict(meta)
        self.save()


def calculate_rollover_score(meta: SessionMeta, context_policy: dict, now: datetime | None = None, force: bool = False, context_error: bool = False) -> int:
    if now is None:
        now = datetime.now(timezone.utc)

    score = 0
    if meta.message_count >= context_policy.get("soft_message_limit", 20):
        score += 40
    if meta.message_count >= context_policy.get("hard_message_limit", 35):
        score += 30

    if meta.created_at:
        created = datetime.fromisoformat(meta.created_at)
        age_hours = (now - created).total_seconds() / 3600
        if age_hours > 24:
            score += 20
        if age_hours > 72:
            score += 20

    if meta.input_chars > 20000:
        score += 30
    if meta.output_chars > 60000:
        score += 30
    if meta.attachment_task_count >= 2:
        score += 20

    if context_error:
        score += 100
    if force:
        score += 100

    return score


def is_rollover_cooled_down(meta: SessionMeta, context_policy: dict, now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)
    if not meta.last_rollover_at:
        return True
    last = datetime.fromisoformat(meta.last_rollover_at)
    cooldown = context_policy.get("rollover_cooldown_hours", 2)
    if (now - last).total_seconds() / 3600 < cooldown:
        return False
    min_messages = context_policy.get("min_messages_between_rollovers", 8)
    if meta.message_count < min_messages:
        return False
    return True
