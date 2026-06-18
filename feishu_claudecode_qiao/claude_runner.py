from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from concurrent.futures import Future
from threading import Lock, Thread
from time import monotonic
from typing import Any, Callable, Protocol


@dataclass
class ClaudeRunRequest:
    prompt: str
    session_id: str | None = None
    cwd: str | None = None
    permission_mode: str | None = None
    session_key: str = ""
    chat_id: str = ""
    on_text: Callable[[str], None] | None = None
    cancel_requested: Callable[[], bool] | None = None


@dataclass
class ClaudeRunResult:
    text: str
    session_id: str | None = None
    error: str = ""
    timing: dict[str, int] = field(default_factory=dict)


class ClaudeRunner(Protocol):
    def run(self, request: ClaudeRunRequest) -> ClaudeRunResult:
        ...


class OneShotClaudeRunner:
    def __init__(
        self,
        call_claude: Callable[..., tuple[str, str | None]],
    ) -> None:
        self._call_claude = call_claude

    def run(self, request: ClaudeRunRequest) -> ClaudeRunResult:
        try:
            text, session_id = self._call_claude(
                request.prompt,
                request.session_id,
                cwd=request.cwd,
                permission_mode=request.permission_mode,
            )
        except Exception as exc:
            return ClaudeRunResult(text="", session_id=request.session_id, error=str(exc))

        if request.on_text and text:
            request.on_text(text)
        return ClaudeRunResult(text=text, session_id=session_id, error="")


class FallbackClaudeRunner:
    def __init__(self, primary: ClaudeRunner, fallback: ClaudeRunner) -> None:
        self.primary = primary
        self.fallback = fallback

    def run(self, request: ClaudeRunRequest) -> ClaudeRunResult:
        primary_result = self.primary.run(request)
        if not primary_result.error:
            return primary_result
        fallback_result = self.fallback.run(request)
        if fallback_result.error:
            fallback_result.error = (
                f"{primary_result.error}; fallback failed: {fallback_result.error}"
            )
        return fallback_result


class ConditionalClaudeRunner:
    def __init__(
        self,
        primary: ClaudeRunner,
        fallback: ClaudeRunner,
        enabled: Callable[[ClaudeRunRequest], bool],
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.enabled = enabled

    def run(self, request: ClaudeRunRequest) -> ClaudeRunResult:
        if self.enabled(request):
            return self.primary.run(request)
        return self.fallback.run(request)


@dataclass
class _PersistentWorker:
    key: str
    client: Any
    last_used: float
    busy: bool = False


class PersistentClaudeRunner:
    """SDK-backed persistent Claude runner.

    The Claude Agent SDK is optional. When it is not installed, this runner
    returns an error and the bridge-level fallback runner can use one-shot CLI.
    """

    def __init__(
        self,
        *,
        client_cls: Any | None = None,
        options_cls: Any | None = None,
        cli_path: str | None = None,
        sdk_available: bool = True,
        idle_ttl_seconds: int = 900,
        max_workers: int = 3,
        now: Callable[[], float] = monotonic,
    ) -> None:
        self._client_cls = client_cls
        self._options_cls = options_cls
        self.cli_path = cli_path
        self.sdk_available = sdk_available
        self.idle_ttl_seconds = idle_ttl_seconds
        self.max_workers = max(1, max_workers)
        self._now = now
        self._workers: dict[str, _PersistentWorker] = {}
        self._sdk_import_error: str = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: Thread | None = None
        self._loop_lock = Lock()

    def run(self, request: ClaudeRunRequest) -> ClaudeRunResult:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._run_async(request),
                self._ensure_loop(),
            )
            return future.result()
        except Exception as exc:
            return ClaudeRunResult(text="", session_id=request.session_id, error=str(exc))

    def cleanup_idle(self) -> None:
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(
            self._cleanup_idle_async(),
            self._ensure_loop(),
        )
        future.result()

    def close_all(self) -> None:
        loop = self._loop
        if loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._close_all_async(), loop)
        future.result()
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            ready: Future[asyncio.AbstractEventLoop] = Future()

            def _run_loop() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                ready.set_result(loop)
                loop.run_forever()
                loop.close()

            self._thread = Thread(
                target=_run_loop,
                name="qiao-claude-sdk-runner",
                daemon=True,
            )
            self._thread.start()
            self._loop = ready.result(timeout=5)
            return self._loop

    async def _run_async(self, request: ClaudeRunRequest) -> ClaudeRunResult:
        await self._cleanup_idle_async()
        worker = await self._worker_for_request(request)
        if worker is None:
            return ClaudeRunResult(
                text="",
                session_id=request.session_id,
                error=self._sdk_import_error or "claude-agent-sdk is not installed",
            )

        worker.busy = True
        try:
            await worker.client.query(request.prompt)
            text, session_id = await self._receive_response(worker.client, request)
            worker.last_used = self._now()
            return ClaudeRunResult(text=text, session_id=session_id or request.session_id)
        finally:
            worker.busy = False

    async def _worker_for_request(
        self,
        request: ClaudeRunRequest,
    ) -> _PersistentWorker | None:
        key = request.session_key or request.chat_id or request.session_id or "__default__"
        worker = self._workers.get(key)
        if worker is not None:
            return worker

        client_cls, options_cls = self._load_sdk()
        if client_cls is None or options_cls is None:
            return None

        await self._evict_if_needed()
        options = self._make_options(options_cls, request)
        client = client_cls(options=options)
        connect = getattr(client, "connect", None)
        if connect:
            await connect()
        worker = _PersistentWorker(key=key, client=client, last_used=self._now())
        self._workers[key] = worker
        return worker

    def _load_sdk(self) -> tuple[Any | None, Any | None]:
        if not self.sdk_available:
            self._sdk_import_error = "claude-agent-sdk is disabled"
            return None, None
        if self._client_cls is not None and self._options_cls is not None:
            return self._client_cls, self._options_cls
        try:
            from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        except Exception as exc:
            self._sdk_import_error = f"claude-agent-sdk is not installed: {exc}"
            return None, None
        self._client_cls = ClaudeSDKClient
        self._options_cls = ClaudeAgentOptions
        return self._client_cls, self._options_cls

    def _make_options(self, options_cls: Any, request: ClaudeRunRequest) -> Any:
        kwargs: dict[str, Any] = {}
        if request.cwd:
            kwargs["cwd"] = request.cwd
        if self.cli_path:
            kwargs["cli_path"] = self.cli_path
        if request.permission_mode:
            kwargs["permission_mode"] = request.permission_mode
        if request.session_id:
            kwargs["resume"] = request.session_id
        try:
            return options_cls(**kwargs)
        except TypeError:
            kwargs.pop("resume", None)
            try:
                return options_cls(**kwargs)
            except TypeError:
                return options_cls()

    async def _receive_response(
        self,
        client: Any,
        request: ClaudeRunRequest,
    ) -> tuple[str, str | None]:
        final_text = ""
        session_id: str | None = None
        receiver = getattr(client, "receive_response")
        stream = receiver()
        async for event in stream:
            chunk, event_session = self._extract_event(event)
            if event_session:
                session_id = event_session
            if chunk:
                final_text += chunk
                if request.on_text:
                    request.on_text(chunk)
        return final_text, session_id

    def _extract_event(self, event: Any) -> tuple[str, str | None]:
        if isinstance(event, dict):
            event_type = event.get("type", "")
            if event_type == "system":
                return "", event.get("session_id")
            if event_type == "assistant":
                return self._text_from_content(event.get("message", {}).get("content")), None
            if event_type == "result":
                return self._text_from_content(event.get("result")), event.get("session_id")
            return "", event.get("session_id")

        event_type = getattr(event, "type", "")
        session_id = getattr(event, "session_id", None)
        if event_type == "system":
            return "", session_id
        content = getattr(getattr(event, "message", None), "content", None)
        if content is None:
            content = getattr(event, "content", None)
        return self._text_from_content(content), session_id

    def _text_from_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                else:
                    text = getattr(item, "text", "")
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        if isinstance(content, dict):
            return str(content.get("text", ""))
        return ""

    async def _cleanup_idle_async(self) -> None:
        now = self._now()
        stale_keys = [
            key
            for key, worker in self._workers.items()
            if not worker.busy and now - worker.last_used >= self.idle_ttl_seconds
        ]
        for key in stale_keys:
            await self._close_worker_async(key)

    async def _evict_if_needed(self) -> None:
        if len(self._workers) < self.max_workers:
            return
        idle_workers = [
            worker for worker in self._workers.values() if not worker.busy
        ]
        if not idle_workers:
            return
        oldest = min(idle_workers, key=lambda worker: worker.last_used)
        await self._close_worker_async(oldest.key)

    async def _close_worker_async(self, key: str) -> None:
        worker = self._workers.pop(key, None)
        if worker is None:
            return
        disconnect = getattr(worker.client, "disconnect", None)
        if disconnect:
            await disconnect()

    async def _close_all_async(self) -> None:
        for key in list(self._workers):
            await self._close_worker_async(key)
