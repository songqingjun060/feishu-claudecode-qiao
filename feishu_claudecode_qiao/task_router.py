from __future__ import annotations

import re
from dataclasses import dataclass, field

from .tasks.local_tool import LocalToolConfig


@dataclass(frozen=True)
class TaskContext:
    chat_id: str
    recent_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskMatch:
    task_kind: str
    confidence: float
    params: dict[str, list[str]]
    tool: LocalToolConfig | None = None


class TaskRouter:
    def __init__(self, local_tools: list[LocalToolConfig] | None = None) -> None:
        self.local_tools = [tool for tool in (local_tools or []) if tool.enabled]

    def match(self, content: str, context: TaskContext) -> TaskMatch | None:
        return self._match_local_tool(content, context)

    def intent_tools(self, content: str) -> list[LocalToolConfig]:
        text = content.strip()
        return [
            tool
            for tool in self.local_tools
            if tool.prompt_hint and _keyword_matches(tool, text)
        ]

    def _match_local_tool(self, content: str, context: TaskContext) -> TaskMatch | None:
        text = content.strip()
        for tool in self.local_tools:
            if not _keyword_matches(tool, text):
                continue
            matches: list[str] = []
            for pattern in tool.match_patterns:
                matches.extend(re.findall(pattern, text, re.IGNORECASE))
            matches = _unique([_flatten_match(match) for match in matches])
            if tool.match_patterns and not matches:
                continue
            return TaskMatch(
                task_kind="local_tool",
                confidence=0.85,
                params={"matches": matches},
                tool=tool,
            )
        return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _keyword_matches(tool: LocalToolConfig, text: str) -> bool:
    if not tool.keywords:
        return True
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in tool.keywords)


def _flatten_match(value) -> str:
    if isinstance(value, tuple):
        return next((str(item) for item in value if item), "")
    return str(value)
