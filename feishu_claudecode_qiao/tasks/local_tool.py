from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LocalToolConfig:
    name: str
    enabled: bool = True
    keywords: list[str] = field(default_factory=list)
    match_patterns: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    cwd: str = "."
    timeout_seconds: int = 180
    health_command: list[str] = field(default_factory=list)
    health_interval_seconds: int = 0
    health_startup_delay_seconds: int = 0
    health_timeout_seconds: int = 15
    refresh_command: list[str] = field(default_factory=list)
    refresh_timeout_seconds: int = 150
    refresh_cooldown_seconds: int = 1800
    attachment_path_fields: list[str] = field(
        default_factory=lambda: ["attachment_path", "file_path", "excelFilePath", "excel_path"]
    )
    summary_fields: list[str] = field(default_factory=lambda: ["summary", "message", "text"])
    context_label: str = "local tool result"
    prompt_hint: str = ""


@dataclass(frozen=True)
class LocalToolRequest:
    tool: LocalToolConfig
    matches: list[str] = field(default_factory=list)
    content: str = ""


@dataclass(frozen=True)
class LocalToolResult:
    ok: bool
    tool_name: str = ""
    summary: str = ""
    attachment_path: str = ""
    raw_output: str = ""
    error: str = ""


@dataclass(frozen=True)
class LocalToolHealthResult:
    ok: bool
    tool_name: str = ""
    status: str = ""
    message: str = ""
    raw_output: str = ""
    error: str = ""


class LocalToolRunner:
    def run(self, request: LocalToolRequest) -> LocalToolResult:
        tool = request.tool
        if not tool.command:
            return LocalToolResult(ok=False, tool_name=tool.name, error=f"本地工具未配置 command: {tool.name}")

        args = _render_command(tool.command, request)
        completed, error = self._run_command(tool, args, tool.timeout_seconds)
        if completed is None:
            return LocalToolResult(ok=False, tool_name=tool.name, error=error)

        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            return LocalToolResult(
                ok=False,
                tool_name=tool.name,
                raw_output=output,
                error=(completed.stderr or output or f"本地工具退出码 {completed.returncode}").strip(),
            )
        return parse_local_tool_output(output, tool)

    def run_health_check(self, tool: LocalToolConfig) -> LocalToolHealthResult:
        if not tool.health_command:
            return LocalToolHealthResult(
                ok=False,
                tool_name=tool.name,
                status="not_configured",
                message="本地工具未配置 health_command",
            )
        return self._run_health_command(tool, tool.health_command, tool.health_timeout_seconds)

    def run_refresh(self, tool: LocalToolConfig) -> LocalToolHealthResult:
        if not tool.refresh_command:
            return LocalToolHealthResult(
                ok=False,
                tool_name=tool.name,
                status="not_configured",
                message="本地工具未配置 refresh_command",
            )
        return self._run_health_command(tool, tool.refresh_command, tool.refresh_timeout_seconds)

    def _run_health_command(
        self,
        tool: LocalToolConfig,
        command: list[str],
        timeout_seconds: int,
    ) -> LocalToolHealthResult:
        completed, error = self._run_command(tool, command, timeout_seconds)
        if completed is None:
            status = "timeout" if "超时" in error else "runner_error"
            return LocalToolHealthResult(
                ok=False,
                tool_name=tool.name,
                status=status,
                message=error,
                error=error,
            )

        output = (completed.stdout or "").strip()
        result = parse_local_tool_health_output(output, tool)
        if completed.returncode != 0 and result.status in {"", "ok"}:
            return LocalToolHealthResult(
                ok=False,
                tool_name=tool.name,
                status="command_failed",
                message=(completed.stderr or output or f"本地工具退出码 {completed.returncode}").strip(),
                raw_output=output,
                error=(completed.stderr or output or f"本地工具退出码 {completed.returncode}").strip(),
            )
        return result

    def _run_command(
        self,
        tool: LocalToolConfig,
        args: list[str],
        timeout_seconds: int,
    ) -> tuple[subprocess.CompletedProcess[str] | None, str]:
        cwd = Path(tool.cwd or ".").expanduser().resolve()
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return None, f"本地工具超时（{timeout_seconds} 秒）：{tool.name}"
        except (OSError, UnicodeError) as exc:
            return None, f"本地工具调用失败：{exc}"
        return completed, ""


def parse_local_tool_output(output: str, tool: LocalToolConfig) -> LocalToolResult:
    text = (output or "").strip()
    if not text:
        return LocalToolResult(ok=False, tool_name=tool.name, error="本地工具没有输出。")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return LocalToolResult(ok=True, tool_name=tool.name, summary=text, raw_output=text)

    ok = payload.get("ok", payload.get("success", True)) is not False
    if not ok:
        return LocalToolResult(
            ok=False,
            tool_name=tool.name,
            raw_output=text,
            error=str(payload.get("error") or payload.get("message") or "本地工具执行失败"),
        )

    summary = _first_string(payload, tool.summary_fields)
    if not summary:
        summary = json.dumps(payload, ensure_ascii=False, indent=2)
    attachment_path = _first_string(payload, tool.attachment_path_fields)
    return LocalToolResult(
        ok=True,
        tool_name=tool.name,
        summary=summary,
        attachment_path=attachment_path,
        raw_output=text,
    )


def parse_local_tool_health_output(output: str, tool: LocalToolConfig) -> LocalToolHealthResult:
    text = (output or "").strip()
    if not text:
        return LocalToolHealthResult(
            ok=False,
            tool_name=tool.name,
            status="empty_output",
            message="本地工具健康检查没有输出。",
        )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return LocalToolHealthResult(
            ok=False,
            tool_name=tool.name,
            status="invalid_output",
            message="本地工具健康检查输出不是 JSON。",
            raw_output=text,
        )

    ok = payload.get("ok", payload.get("success", False)) is True
    status = str(payload.get("status") or ("ok" if ok else "failed"))
    message = str(payload.get("message") or payload.get("error") or status)
    return LocalToolHealthResult(
        ok=ok,
        tool_name=tool.name,
        status=status,
        message=message,
        raw_output=text,
        error="" if ok else message,
    )


def _render_command(command: list[str], request: LocalToolRequest) -> list[str]:
    matches = request.matches
    values = {
        "content": request.content,
        "match": matches[0] if matches else "",
        "matches": ",".join(matches),
    }
    return [str(part).format(**values) for part in command]


def _first_string(payload: dict[str, Any], fields: list[str]) -> str:
    for field_name in fields:
        value = payload.get(field_name)
        if value:
            return str(value)
    return ""
