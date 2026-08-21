"""Background health checks for configured local tools."""

from __future__ import annotations

import time
from threading import Event, Thread
from typing import Any

from .tasks.local_tool import LocalToolConfig, LocalToolHealthResult, LocalToolRunner


class LocalToolHealthMonitor:
    """Runs optional local-tool probes without blocking Feishu event handling."""

    def __init__(
        self,
        tools: list[LocalToolConfig],
        runner: LocalToolRunner,
        logger: Any,
        audit: Any,
    ) -> None:
        self.tools = [
            tool
            for tool in tools
            if tool.enabled and tool.health_command and tool.health_interval_seconds > 0
        ]
        self.runner = runner
        self.logger = logger
        self.audit = audit
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._last_refresh_at: dict[str, float] = {}

    def start(self) -> bool:
        if not self.tools or self._thread is not None:
            return False
        self._thread = Thread(
            target=self._run,
            name="local-tool-health",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def check_once(self, tool: LocalToolConfig, *, now: float | None = None) -> None:
        checked_at = time.time() if now is None else now
        health = self.runner.run_health_check(tool)
        self._record_health(tool, health)
        if health.status != "auth_expired" or not tool.refresh_command:
            return

        cooldown = max(0, int(tool.refresh_cooldown_seconds))
        last_refresh = self._last_refresh_at.get(tool.name)
        if last_refresh is not None and checked_at - last_refresh < cooldown:
            self._record_refresh_skipped(tool, cooldown)
            return

        self._last_refresh_at[tool.name] = checked_at
        refresh = self.runner.run_refresh(tool)
        self._record_refresh(tool, refresh)
        if refresh.ok:
            self._record_health(tool, self.runner.run_health_check(tool))

    def _run(self) -> None:
        next_check = {
            tool.name: time.monotonic() + max(0, int(tool.health_startup_delay_seconds))
            for tool in self.tools
        }
        while not self._stop_event.is_set():
            now = time.monotonic()
            due_tools = [tool for tool in self.tools if now >= next_check[tool.name]]
            for tool in due_tools:
                self.check_once(tool)
                next_check[tool.name] = time.monotonic() + max(1, int(tool.health_interval_seconds))

            if not self.tools:
                return
            next_due = min(next_check.values())
            self._stop_event.wait(max(0.1, min(5.0, next_due - time.monotonic())))

    def _record_health(self, tool: LocalToolConfig, result: LocalToolHealthResult) -> None:
        self.audit.write(
            "local_tool_health",
            tool=tool.name,
            status=result.status,
            ok=result.ok,
            message=result.message,
        )
        message = f"Local tool health: tool={tool.name} status={result.status} message={result.message}"
        if result.ok:
            self.logger.info(message)
        else:
            self.logger.warning(message)

    def _record_refresh(self, tool: LocalToolConfig, result: LocalToolHealthResult) -> None:
        self.audit.write(
            "local_tool_auth_refresh",
            tool=tool.name,
            status=result.status,
            ok=result.ok,
            message=result.message,
        )
        message = f"Local tool auth refresh: tool={tool.name} status={result.status} message={result.message}"
        if result.ok:
            self.logger.info(message)
        else:
            self.logger.warning(message)

    def _record_refresh_skipped(self, tool: LocalToolConfig, cooldown: int) -> None:
        self.audit.write(
            "local_tool_auth_refresh_skipped",
            tool=tool.name,
            reason="cooldown",
            cooldown_seconds=cooldown,
        )
        self.logger.warning(
            f"Local tool auth refresh skipped by cooldown: tool={tool.name} cooldown_seconds={cooldown}"
        )
