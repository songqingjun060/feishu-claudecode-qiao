"""Security boundary controls for feishu-claudecode-qiao."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PathCheckResult:
    allowed: bool
    reason: str = ""
    matched_pattern: str = ""
    matched_allowed_dir: str = ""


@dataclass
class RiskCheckResult:
    risky: bool
    category: str = ""
    reason: str = ""


def extract_path_candidates(content: str) -> list[str]:
    """Extract obvious local path candidates from message text."""
    patterns = [
        r"[A-Za-z]:[\\/][^\s`'\"<>|]+",
        r"(?:\./|\.\./)[^\s`'\"<>|]+",
        r"/(?:[A-Za-z0-9._~-]+/)+[A-Za-z0-9._~-]+",
    ]
    found: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, content):
            candidate = match.rstrip("，。；;,.\n")
            if candidate and candidate not in found:
                found.append(candidate)
    return found


class SecurityPolicy:
    """Manages security boundaries: permission mode, file access, message filtering."""

    # System-sensitive paths that should never be accessed
    _BLOCKED_PATH_PATTERNS = [
        r"^[A-Za-z]:[/\\]Windows",
        r"^[A-Za-z]:[/\\]Program Files",
        r"^[A-Za-z]:[/\\]ProgramData",
        r"^/etc",
        r"^/usr",
        r"^/bin",
        r"^/sbin",
        r"^/root",
        r"\.ssh",
        r"\.gnupg",
        r"\.aws",
        r"\.kube",
        r"password",
        r"secret",
        r"token",
    ]

    def __init__(
        self,
        permission_mode: str = "bypassPermissions",
        allowed_paths: list[str] | None = None,
        blocked_keywords: list[str] | None = None,
        work_dir: str = ".",
        data_dir: str = "data",
    ) -> None:
        self.permission_mode = permission_mode
        self.work_dir = Path(work_dir).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.allowed_paths = [Path(p).resolve() for p in (allowed_paths or [])]
        self.blocked_keywords = [kw.strip().lower() for kw in (blocked_keywords or []) if kw.strip()]
        self._blocked_pattern = re.compile(
            "|".join(re.escape(kw) for kw in self.blocked_keywords),
            re.IGNORECASE,
        ) if self.blocked_keywords else None

    def get_claude_permission_args(self) -> list[str]:
        """Return CLI args for Claude permission mode."""
        if self.permission_mode and self.permission_mode != "bypassPermissions":
            return ["--permission-mode", self.permission_mode]
        return []

    def _blocked_path_match(self, path: str) -> str:
        for pattern in self._BLOCKED_PATH_PATTERNS:
            if re.search(pattern, path, re.IGNORECASE):
                return pattern
        return ""

    def is_path_allowed(self, path: str | Path) -> bool:
        """Check if a file path is within allowed directories."""
        raw_path = str(path)
        if self._blocked_path_match(raw_path):
            return False

        try:
            target = Path(path).resolve()
        except (OSError, ValueError):
            return False

        # Check blocked patterns
        path_str = str(target)
        if self._blocked_path_match(path_str):
            return False

        # Check if within default allowed dirs
        allowed_dirs = [self.work_dir, self.data_dir] + self.allowed_paths
        for allowed in allowed_dirs:
            try:
                target.relative_to(allowed)
                return True
            except ValueError:
                continue

        return False

    def explain_path(self, path: str | Path) -> PathCheckResult:
        """Explain why a path is allowed or blocked."""
        raw_path = str(path)
        raw_pattern = self._blocked_path_match(raw_path)
        if raw_pattern:
            return PathCheckResult(
                allowed=False,
                reason="Path matches a blocked system pattern",
                matched_pattern=raw_pattern,
            )

        try:
            target = Path(path).resolve()
        except (OSError, ValueError) as e:
            return PathCheckResult(allowed=False, reason=f"Invalid path: {e}")

        path_str = str(target)

        # Check blocked patterns
        resolved_pattern = self._blocked_path_match(path_str)
        if resolved_pattern:
            return PathCheckResult(
                allowed=False,
                reason="Path matches a blocked system pattern",
                matched_pattern=resolved_pattern,
            )

        # Check if within default allowed dirs
        allowed_dirs = [self.work_dir, self.data_dir] + self.allowed_paths
        for allowed in allowed_dirs:
            try:
                target.relative_to(allowed)
                return PathCheckResult(
                    allowed=True,
                    reason="Path is within allowed directory",
                    matched_allowed_dir=str(allowed),
                )
            except ValueError:
                continue

        return PathCheckResult(
            allowed=False,
            reason="Path is outside all allowed directories",
        )

    def check_message(self, content: str) -> tuple[bool, str]:
        """Check message for blocked keywords.

        Returns:
            (is_blocked, warning_message)
            If not blocked, warning_message is empty.
        """
        if not self.blocked_keywords or not self._blocked_pattern:
            return False, ""

        if self._blocked_pattern.search(content):
            keywords = ", ".join(self.blocked_keywords)
            return True, (
                f"⚠️ 消息已被拦截："
                f"检测到敏感关键词 ({keywords})。"
                f"请避免在群聊中发送包含这些内容的消息。"
            )

        return False, ""

    def check_risky_intent(self, content: str) -> RiskCheckResult:
        """Detect risky operations in message content."""
        text = content.lower()
        patterns = [
            ("delete", [r"\brm\s+-rf\b", "删除", "删掉", "delete"]),
            ("move", ["移动", "move ", "mv "]),
            ("overwrite", ["覆盖", "overwrite", "> "]),
            ("read_sensitive", [".ssh", ".aws", ".kube", "id_rsa", "password", "secret", "token"]),
            ("shell", ["powershell", "cmd.exe", "bash", "sudo", "curl |", "invoke-expression"]),
        ]
        for category, needles in patterns:
            for needle in needles:
                if needle.startswith(r"\b"):
                    if re.search(needle, text, re.IGNORECASE):
                        return RiskCheckResult(True, category, f"命中危险操作模式: {needle}")
                elif needle.lower() in text:
                    return RiskCheckResult(True, category, f"命中危险关键词: {needle}")
        return RiskCheckResult(False)
