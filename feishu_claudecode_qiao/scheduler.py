from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from uuid import uuid4


@dataclass
class QueuePolicy:
    queue_notice_after_seconds: int = 8


@dataclass
class QueuedMessage:
    chat_id: str
    message_id: str
    sender_id: str
    content: str
    created_at: float


@dataclass
class ChatRun:
    run_id: str
    chat_id: str
    message_ids: list[str]
    sender_id: str
    content: str
    status: str = "running"
    started_at: float = 0.0
    updated_at: float = 0.0
    cancel_requested: bool = False
    current_stage: str = "received"
    runner_kind: str = "oneshot"


@dataclass
class EnqueueResult:
    started: bool
    run: ChatRun | None
    queue_position: int = 0


@dataclass
class ChatStatus:
    chat_id: str
    active_run_id: str = ""
    active_status: str = ""
    queued_count: int = 0


@dataclass
class _ChatState:
    active: ChatRun | None = None
    queue: list[QueuedMessage] = field(default_factory=list)
    queue_notice_sent: bool = False


class ChatScheduler:
    def __init__(self, policy: QueuePolicy | None = None) -> None:
        self.policy = policy or QueuePolicy()
        self._states: dict[str, _ChatState] = {}
        self._run_to_chat: dict[str, str] = {}

    def enqueue(
        self,
        *,
        chat_id: str,
        message_id: str,
        sender_id: str,
        content: str,
        now: float | None = None,
    ) -> EnqueueResult:
        timestamp = time() if now is None else now
        state = self._states.setdefault(chat_id, _ChatState())
        if state.active is None:
            run = self._new_run(chat_id, [message_id], sender_id, content, timestamp)
            state.active = run
            self._run_to_chat[run.run_id] = chat_id
            state.queue_notice_sent = False
            return EnqueueResult(started=True, run=run, queue_position=0)

        state.queue.append(
            QueuedMessage(
                chat_id=chat_id,
                message_id=message_id,
                sender_id=sender_id,
                content=content,
                created_at=timestamp,
            )
        )
        return EnqueueResult(started=False, run=None, queue_position=len(state.queue))

    def finish(self, run_id: str, *, now: float | None = None) -> ChatRun | None:
        chat_id = self._run_to_chat.pop(run_id, "")
        if not chat_id:
            return None
        state = self._states.setdefault(chat_id, _ChatState())
        state.active = None
        if not state.queue:
            state.queue_notice_sent = False
            return None
        message = state.queue.pop(0)
        timestamp = time() if now is None else now
        run = self._new_run(
            chat_id,
            [message.message_id],
            message.sender_id,
            message.content,
            timestamp,
        )
        state.active = run
        state.queue_notice_sent = False
        self._run_to_chat[run.run_id] = chat_id
        return run

    def cancel(self, chat_id: str) -> bool:
        state = self._states.get(chat_id)
        if not state or not state.active:
            return False
        state.active.cancel_requested = True
        state.active.status = "cancelling"
        state.active.updated_at = time()
        return True

    def status(self, chat_id: str) -> ChatStatus:
        state = self._states.get(chat_id)
        if not state:
            return ChatStatus(chat_id=chat_id)
        active = state.active
        return ChatStatus(
            chat_id=chat_id,
            active_run_id=active.run_id if active else "",
            active_status=active.status if active else "",
            queued_count=len(state.queue),
        )

    def should_notice_queue(self, chat_id: str, *, now: float | None = None) -> bool:
        state = self._states.get(chat_id)
        if not state or not state.queue or state.queue_notice_sent:
            return False
        timestamp = time() if now is None else now
        oldest = state.queue[0]
        if timestamp - oldest.created_at < self.policy.queue_notice_after_seconds:
            return False
        state.queue_notice_sent = True
        return True

    def active_runs(self) -> list[ChatRun]:
        return [
            state.active
            for state in self._states.values()
            if state.active is not None
        ]

    def start_run(
        self,
        *,
        chat_id: str,
        message_id: str,
        sender_id: str,
        content: str,
        now: float | None = None,
    ) -> ChatRun:
        timestamp = time() if now is None else now
        state = self._states.setdefault(chat_id, _ChatState())
        if state.active is not None:
            return state.active
        run = self._new_run(chat_id, [message_id], sender_id, content, timestamp)
        state.active = run
        self._run_to_chat[run.run_id] = chat_id
        return run

    def update_stage(self, run_id: str, stage: str) -> None:
        chat_id = self._run_to_chat.get(run_id, "")
        if not chat_id:
            return
        state = self._states.get(chat_id)
        if not state or not state.active:
            return
        state.active.current_stage = stage
        state.active.updated_at = time()

    def _new_run(
        self,
        chat_id: str,
        message_ids: list[str],
        sender_id: str,
        content: str,
        now: float,
    ) -> ChatRun:
        return ChatRun(
            run_id=f"run_{uuid4().hex}",
            chat_id=chat_id,
            message_ids=message_ids,
            sender_id=sender_id,
            content=content,
            started_at=now,
            updated_at=now,
        )
