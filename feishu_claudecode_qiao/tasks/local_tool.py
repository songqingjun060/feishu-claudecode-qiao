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


class LocalToolRunner:
    def run(self, request: LocalToolRequest) -> LocalToolResult:
        tool = request.tool
        if not tool.command:
            return LocalToolResult(ok=False, tool_name=tool.name, error=f"本地工具未配置 command: {tool.name}")

        args = _render_command(tool.command, request)
        cwd = Path(tool.cwd or ".").expanduser().resolve()
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=tool.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return LocalToolResult(ok=False, tool_name=tool.name, error=f"本地工具超时（{tool.timeout_seconds} 秒）：{tool.name}")
        except (OSError, UnicodeError) as exc:
            return LocalToolResult(ok=False, tool_name=tool.name, error=f"本地工具调用失败：{exc}")

        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            return LocalToolResult(
                ok=False,
                tool_name=tool.name,
                raw_output=output,
                error=(completed.stderr or output or f"本地工具退出码 {completed.returncode}").strip(),
            )
        return parse_local_tool_output(output, tool)


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
