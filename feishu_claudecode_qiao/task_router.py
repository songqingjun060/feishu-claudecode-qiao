from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskContext:
    chat_id: str
    recent_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskMatch:
    task_kind: str
    confidence: float
    params: dict[str, list[str]]


class TaskRouter:
    def match(self, content: str, context: TaskContext) -> TaskMatch | None:
        return self._match_bi_logistics(content, context)

    def _match_bi_logistics(self, content: str, context: TaskContext) -> TaskMatch | None:
        text = content.strip()
        lowered = text.lower()
        bi_words = ("bi", "物流码", "wms", "配货单", "来源单")
        query_words = ("查询", "查", "核对", "批量", "明细", "query", "search")
        has_bi_intent = any(word in lowered for word in bi_words) and any(
            word in lowered for word in query_words
        )
        if not has_bi_intent:
            return None

        sources = _unique(re.findall(r"\bQ\d{8,}[-/][0-9A-Za-z/-]+\b", text, re.IGNORECASE))
        wms_orders = _unique(re.findall(r"\b(?:CK|RK)?\d{8,}[A-Za-z0-9/-]*\b", text, re.IGNORECASE))
        codes = _unique(re.findall(r"\b\d{11,24}\b", text))

        if sources:
            return TaskMatch(
                task_kind="bi_logistics",
                confidence=0.9,
                params={"sources": sources, "codes": [], "wms_orders": []},
            )
        if codes:
            return TaskMatch(
                task_kind="bi_logistics",
                confidence=0.85,
                params={"sources": [], "codes": codes, "wms_orders": []},
            )
        if wms_orders and "wms" in lowered:
            return TaskMatch(
                task_kind="bi_logistics",
                confidence=0.8,
                params={"sources": [], "codes": [], "wms_orders": wms_orders},
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
