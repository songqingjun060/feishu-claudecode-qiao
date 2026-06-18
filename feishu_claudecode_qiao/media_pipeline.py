from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from uuid import uuid4


@dataclass
class MediaItem:
    kind: str
    message_id: str
    path: str = ""
    file_name: str = ""


@dataclass
class MediaBatch:
    batch_id: str
    chat_id: str
    chat_type: str
    sender_id: str
    created_at: float
    updated_at: float
    items: list[MediaItem] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    message_ids: list[str] = field(default_factory=list)


class MediaBatcher:
    def __init__(self, window_seconds: int = 10) -> None:
        self.window_seconds = window_seconds
        self._batches: dict[tuple[str, str], MediaBatch] = {}

    def add_media(
        self,
        *,
        chat_id: str,
        chat_type: str,
        sender_id: str,
        item: MediaItem,
        now: float | None = None,
    ) -> MediaBatch:
        timestamp = time() if now is None else now
        batch = self._get_or_create(chat_id, chat_type, sender_id, timestamp)
        batch.items.append(item)
        batch.message_ids.append(item.message_id)
        batch.updated_at = timestamp
        return batch

    def add_text(
        self,
        *,
        chat_id: str,
        chat_type: str,
        sender_id: str,
        message_id: str,
        text: str,
        mentioned: bool,
        reply_to_bot: bool,
        now: float | None = None,
    ) -> MediaBatch:
        timestamp = time() if now is None else now
        can_merge_group = chat_type != "group" or mentioned or reply_to_bot
        batch = self._find_current(chat_id, sender_id, timestamp) if can_merge_group else None
        if batch is None:
            batch = self._create(
                chat_id,
                chat_type,
                sender_id,
                timestamp,
                store=can_merge_group,
            )
        if text.strip():
            batch.texts.append(text.strip())
        batch.message_ids.append(message_id)
        batch.updated_at = timestamp
        return batch

    def current_batch(
        self,
        *,
        chat_id: str,
        sender_id: str,
        now: float | None = None,
    ) -> MediaBatch | None:
        timestamp = time() if now is None else now
        return self._find_current(chat_id, sender_id, timestamp)

    def render_context(self, batch: MediaBatch) -> str:
        if not batch.items and not batch.texts:
            return ""
        lines = [
            "\n\n<bridge_media_batch>",
            f"batch_id: {batch.batch_id}",
            f"chat_id: {batch.chat_id}",
            f"sender_id: {batch.sender_id}",
        ]
        if batch.texts:
            lines.append("texts:")
            for text in batch.texts:
                lines.append(f"- {text}")
        if batch.items:
            lines.append("files:")
            for item in batch.items:
                lines.append(f"- kind: {item.kind}")
                lines.append(f"  message_id: {item.message_id}")
                if item.file_name:
                    lines.append(f"  file_name: {item.file_name}")
                if item.path:
                    lines.append(f"  path: {item.path}")
        lines.append(
            "instruction: 这些是同一聊天窗口内短时间连续发送的图片或文件。请把它们作为同一个任务的上下文处理，不要只读取最后一个文件。"
        )
        lines.append("</bridge_media_batch>")
        return "\n".join(lines)

    def _get_or_create(
        self,
        chat_id: str,
        chat_type: str,
        sender_id: str,
        now: float,
    ) -> MediaBatch:
        return self._find_current(chat_id, sender_id, now) or self._create(
            chat_id,
            chat_type,
            sender_id,
            now,
        )

    def _find_current(
        self,
        chat_id: str,
        sender_id: str,
        now: float,
    ) -> MediaBatch | None:
        batch = self._batches.get((chat_id, sender_id))
        if not batch:
            return None
        if now - batch.updated_at > self.window_seconds:
            return None
        return batch

    def _create(
        self,
        chat_id: str,
        chat_type: str,
        sender_id: str,
        now: float,
        *,
        store: bool = True,
    ) -> MediaBatch:
        batch = MediaBatch(
            batch_id=f"batch_{uuid4().hex}",
            chat_id=chat_id,
            chat_type=chat_type,
            sender_id=sender_id,
            created_at=now,
            updated_at=now,
        )
        if store:
            self._batches[(chat_id, sender_id)] = batch
        return batch


@dataclass
class RecentGeneratedFile:
    path: str
    source_message_id: str = ""
    uploaded: bool = False
    created_at: float = 0.0


class RecentContext:
    def __init__(self) -> None:
        self._generated_files: dict[str, list[RecentGeneratedFile]] = {}

    def remember_generated_file(
        self,
        chat_id: str,
        path: str,
        *,
        source_message_id: str = "",
        uploaded: bool = False,
        now: float | None = None,
    ) -> None:
        timestamp = time() if now is None else now
        files = self._generated_files.setdefault(chat_id, [])
        files.append(
            RecentGeneratedFile(
                path=path,
                source_message_id=source_message_id,
                uploaded=uploaded,
                created_at=timestamp,
            )
        )

    def latest_generated_file(self, chat_id: str) -> RecentGeneratedFile | None:
        files = self._generated_files.get(chat_id, [])
        return files[-1] if files else None

    def mark_uploaded(self, chat_id: str, path: str) -> None:
        for item in reversed(self._generated_files.get(chat_id, [])):
            if item.path == path:
                item.uploaded = True
                return
