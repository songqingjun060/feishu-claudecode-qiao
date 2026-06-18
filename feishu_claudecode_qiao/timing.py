from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class RunTiming:
    run_id: str
    _marks: list[tuple[str, float]] = field(default_factory=list)

    def mark(self, stage: str) -> None:
        self._marks.append((stage, perf_counter()))

    def add_elapsed_mark(self, stage: str, elapsed_ms: int) -> None:
        base = self._marks[-1][1] if self._marks else perf_counter()
        self._marks.append((stage, base + max(0, elapsed_ms) / 1000))

    def stage_ms(self) -> dict[str, int]:
        durations: dict[str, int] = {}
        for (start_name, start_time), (end_name, end_time) in zip(
            self._marks,
            self._marks[1:],
        ):
            key = f"{start_name}_to_{end_name}"
            durations[key] = max(0, int((end_time - start_time) * 1000))
        return durations

    def marks(self) -> list[str]:
        return [name for name, _ in self._marks]
