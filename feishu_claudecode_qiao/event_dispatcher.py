from __future__ import annotations

from queue import Empty, Queue
from threading import Lock, Thread
from time import time
from typing import Any, Callable


CoalescedEvents = dict[str, Any] | list[dict[str, Any]]
CoalesceFn = Callable[[list[dict[str, Any]]], CoalescedEvents]


class ChatEventDispatcher:
    """Dispatch events to one serial worker per chat."""

    def __init__(
        self,
        process: Callable[[dict[str, Any]], None],
        *,
        coalesce: CoalesceFn | None = None,
        before_process: Callable[[dict[str, Any]], None] | None = None,
        coalesce_window_seconds: float = 0.0,
    ) -> None:
        self.process = process
        self.coalesce = coalesce
        self.before_process = before_process
        self.coalesce_window_seconds = max(0.0, float(coalesce_window_seconds))
        self._queues: dict[str, Queue[dict[str, Any] | None]] = {}
        self._threads: dict[str, Thread] = {}
        self._last_used: dict[str, float] = {}
        self._lock = Lock()
        self._stopping = False

    def dispatch(self, event: dict[str, Any]) -> None:
        chat_id = self._chat_id(event)
        with self._lock:
            if self._stopping:
                return
            queue = self._queues.get(chat_id)
            if queue is None:
                queue = Queue()
                self._queues[chat_id] = queue
            thread = self._threads.get(chat_id)
            if thread is None or not thread.is_alive():
                thread = Thread(
                    target=self._worker,
                    args=(chat_id, queue),
                    name=f"qiao-chat-worker-{chat_id[-8:] or 'default'}",
                    daemon=True,
                )
                self._threads[chat_id] = thread
                thread.start()
            queue.put(event)
            self._last_used[chat_id] = time()

    def wait_idle(self, timeout: float = 5.0) -> bool:
        deadline = time() + timeout
        while time() < deadline:
            with self._lock:
                queues = list(self._queues.values())
            if all(queue.unfinished_tasks == 0 for queue in queues):
                return True
        return False

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stopping = True
            items = list(self._queues.items())
            threads = list(self._threads.values())
        for _, queue in items:
            queue.put(None)
        deadline = time() + timeout
        for thread in threads:
            remaining = max(0.0, deadline - time())
            thread.join(timeout=remaining)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "workers": sum(1 for thread in self._threads.values() if thread.is_alive()),
                "queued": sum(queue.qsize() for queue in self._queues.values()),
            }

    def _worker(self, chat_id: str, queue: Queue[dict[str, Any] | None]) -> None:
        while True:
            task_count = 1
            try:
                event = queue.get(timeout=1)
            except Empty:
                continue
            try:
                if event is None:
                    return
                events = [event]
                if self.coalesce and self.coalesce_window_seconds > 0:
                    events.extend(self._drain_coalesce_window(queue))
                    task_count = len(events)
                    coalesced = self.coalesce(events)
                else:
                    coalesced = event
                if isinstance(coalesced, list):
                    for item in coalesced:
                        if self.before_process:
                            self.before_process(item)
                        self.process(item)
                else:
                    if self.before_process:
                        self.before_process(coalesced)
                    self.process(coalesced)
            finally:
                for _ in range(task_count):
                    queue.task_done()
                self._last_used[chat_id] = time()

    def _drain_coalesce_window(
        self,
        queue: Queue[dict[str, Any] | None],
    ) -> list[dict[str, Any]]:
        deadline = time() + self.coalesce_window_seconds
        events: list[dict[str, Any]] = []
        while True:
            remaining = deadline - time()
            if remaining <= 0:
                return events
            try:
                event = queue.get(timeout=remaining)
            except Empty:
                return events
            if event is None:
                queue.put(None)
                return events
            events.append(event)

    def _chat_id(self, event: dict[str, Any]) -> str:
        message = event.get("event", {}).get("message", {})
        chat_id = str(message.get("chat_id") or "")
        if chat_id:
            return chat_id
        return "__unknown__"
