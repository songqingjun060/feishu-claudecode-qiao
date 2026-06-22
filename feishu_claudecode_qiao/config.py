"""Configuration loader: reads config.toml, allows env overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tasks.local_tool import LocalToolConfig


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # python >= 3.11
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    with path.open("rb") as f:
        return tomllib.load(f)


@dataclass(frozen=True)
class Config:
    """Application configuration."""

    # Feishu
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_domain: str = "https://open.feishu.cn"
    feishu_gateway_backend: str = "current"
    feishu_event_backend: str = "start_ws"

    # Claude
    claude_command: str = "claude"
    claude_work_dir: str = "."
    claude_permission_mode: str = "bypassPermissions"
    claude_runner: str = "oneshot"
    claude_worker_idle_ttl_seconds: int = 900
    claude_max_workers: int = 3
    claude_persistent_enabled_chats: list[str] = field(default_factory=list)

    # Whisper
    whisper_model: str = "base"
    whisper_load_policy: str = "preload"

    # Bridge
    bridge_data_dir: str = "./data"
    bridge_log_level: str = "INFO"
    bridge_max_upload_mb: int = 20
    bridge_require_mention_in_group: bool = True
    bridge_bot_display_name: str = ""
    bridge_personal_permission_profile: str = "admin"
    bridge_bot_owner_id: str = ""
    bridge_bot_admins: list[str] = field(default_factory=list)
    bridge_ws_profile: str = "qiao-test"
    bridge_ws_watchdog_interval_seconds: int = 30
    bridge_ws_max_restart_failures: int = 3
    bridge_console_message_log: bool = True
    bridge_console_claude_stream: bool = True
    bridge_queue_notice_after_seconds: int = 8
    bridge_media_batch_window_seconds: int = 10
    bridge_message_coalesce_window_seconds: int = 10
    bridge_text_coalesce_window_seconds: int = 2
    bridge_progress_cards: bool = False
    bridge_fast_tasks_enabled: bool = True
    bridge_local_tools: list[LocalToolConfig] = field(default_factory=list)

    # Security
    security_allowed_paths: list[str] = field(default_factory=list)
    security_blocked_keywords: list[str] = field(default_factory=list)


def _env_override(cfg: Config) -> Config:
    """Apply FEISHUCLAUDECODE_* environment variable overrides."""
    env = os.environ

    def _get(key: str, default: Any) -> Any:
        val = env.get(key)
        if val is None:
            return default
        if isinstance(default, bool):
            return val.lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(val)
        if isinstance(default, list):
            return [v.strip() for v in val.split(",") if v.strip()]
        return val

    return Config(
        feishu_app_id=_get("FEISHUCLAUDECODE_FEISHU_APP_ID", cfg.feishu_app_id),
        feishu_app_secret=_get("FEISHUCLAUDECODE_FEISHU_APP_SECRET", cfg.feishu_app_secret),
        feishu_domain=_get("FEISHUCLAUDECODE_FEISHU_DOMAIN", cfg.feishu_domain),
        feishu_gateway_backend=_get("FEISHUCLAUDECODE_FEISHU_GATEWAY_BACKEND", cfg.feishu_gateway_backend),
        feishu_event_backend=_get("FEISHUCLAUDECODE_FEISHU_EVENT_BACKEND", cfg.feishu_event_backend),
        claude_command=_get("FEISHUCLAUDECODE_CLAUDE_COMMAND", cfg.claude_command),
        claude_work_dir=_get("FEISHUCLAUDECODE_CLAUDE_WORK_DIR", cfg.claude_work_dir),
        claude_permission_mode=_get("FEISHUCLAUDECODE_CLAUDE_PERMISSION_MODE", cfg.claude_permission_mode),
        claude_runner=_get("FEISHUCLAUDECODE_CLAUDE_RUNNER", cfg.claude_runner),
        claude_worker_idle_ttl_seconds=_get("FEISHUCLAUDECODE_CLAUDE_WORKER_IDLE_TTL_SECONDS", cfg.claude_worker_idle_ttl_seconds),
        claude_max_workers=_get("FEISHUCLAUDECODE_CLAUDE_MAX_WORKERS", cfg.claude_max_workers),
        claude_persistent_enabled_chats=_get("FEISHUCLAUDECODE_CLAUDE_PERSISTENT_ENABLED_CHATS", cfg.claude_persistent_enabled_chats),
        whisper_model=_get("FEISHUCLAUDECODE_WHISPER_MODEL", cfg.whisper_model),
        whisper_load_policy=_get("FEISHUCLAUDECODE_WHISPER_LOAD_POLICY", cfg.whisper_load_policy),
        bridge_data_dir=_get("FEISHUCLAUDECODE_BRIDGE_DATA_DIR", cfg.bridge_data_dir),
        bridge_log_level=_get("FEISHUCLAUDECODE_BRIDGE_LOG_LEVEL", cfg.bridge_log_level),
        bridge_max_upload_mb=_get("FEISHUCLAUDECODE_BRIDGE_MAX_UPLOAD_MB", cfg.bridge_max_upload_mb),
        bridge_require_mention_in_group=_get("FEISHUCLAUDECODE_BRIDGE_REQUIRE_MENTION_IN_GROUP", cfg.bridge_require_mention_in_group),
        bridge_bot_display_name=_get("FEISHUCLAUDECODE_BRIDGE_BOT_DISPLAY_NAME", cfg.bridge_bot_display_name),
        bridge_personal_permission_profile=_get("FEISHUCLAUDECODE_BRIDGE_PERSONAL_PERMISSION_PROFILE", cfg.bridge_personal_permission_profile),
        bridge_bot_owner_id=_get("FEISHUCLAUDECODE_BRIDGE_BOT_OWNER_ID", cfg.bridge_bot_owner_id),
        bridge_bot_admins=_get("FEISHUCLAUDECODE_BRIDGE_BOT_ADMINS", cfg.bridge_bot_admins),
        bridge_ws_profile=_get("FEISHUCLAUDECODE_BRIDGE_WS_PROFILE", cfg.bridge_ws_profile),
        bridge_ws_watchdog_interval_seconds=_get("FEISHUCLAUDECODE_BRIDGE_WS_WATCHDOG_INTERVAL_SECONDS", cfg.bridge_ws_watchdog_interval_seconds),
        bridge_ws_max_restart_failures=_get("FEISHUCLAUDECODE_BRIDGE_WS_MAX_RESTART_FAILURES", cfg.bridge_ws_max_restart_failures),
        bridge_console_message_log=_get("FEISHUCLAUDECODE_BRIDGE_CONSOLE_MESSAGE_LOG", cfg.bridge_console_message_log),
        bridge_console_claude_stream=_get("FEISHUCLAUDECODE_BRIDGE_CONSOLE_CLAUDE_STREAM", cfg.bridge_console_claude_stream),
        bridge_queue_notice_after_seconds=_get("FEISHUCLAUDECODE_BRIDGE_QUEUE_NOTICE_AFTER_SECONDS", cfg.bridge_queue_notice_after_seconds),
        bridge_media_batch_window_seconds=_get("FEISHUCLAUDECODE_BRIDGE_MEDIA_BATCH_WINDOW_SECONDS", cfg.bridge_media_batch_window_seconds),
        bridge_message_coalesce_window_seconds=_get("FEISHUCLAUDECODE_BRIDGE_MESSAGE_COALESCE_WINDOW_SECONDS", cfg.bridge_message_coalesce_window_seconds),
        bridge_text_coalesce_window_seconds=_get("FEISHUCLAUDECODE_BRIDGE_TEXT_COALESCE_WINDOW_SECONDS", cfg.bridge_text_coalesce_window_seconds),
        bridge_progress_cards=_get("FEISHUCLAUDECODE_BRIDGE_PROGRESS_CARDS", cfg.bridge_progress_cards),
        bridge_fast_tasks_enabled=_get("FEISHUCLAUDECODE_BRIDGE_FAST_TASKS_ENABLED", cfg.bridge_fast_tasks_enabled),
        bridge_local_tools=cfg.bridge_local_tools,
        security_allowed_paths=_get("FEISHUCLAUDECODE_SECURITY_ALLOWED_PATHS", cfg.security_allowed_paths),
        security_blocked_keywords=_get("FEISHUCLAUDECODE_SECURITY_BLOCKED_KEYWORDS", cfg.security_blocked_keywords),
    )


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from config.toml and apply env overrides.

    Args:
        path: Path to config.toml. Defaults to ``config.toml`` in cwd.
    """
    if path is None:
        path = Path("config.toml")
    else:
        path = Path(path)

    if not path.exists():
        cfg = Config()
    else:
        data = _load_toml(path)
        cfg = Config(
            feishu_app_id=data.get("feishu", {}).get("app_id", ""),
            feishu_app_secret=data.get("feishu", {}).get("app_secret", ""),
            feishu_domain=data.get("feishu", {}).get("domain", "https://open.feishu.cn"),
            feishu_gateway_backend=data.get("feishu", {}).get("gateway_backend", "current"),
            feishu_event_backend=data.get("feishu", {}).get("event_backend", "start_ws"),
            claude_command=data.get("claude", {}).get("command", "claude"),
            claude_work_dir=data.get("claude", {}).get("work_dir", "."),
            claude_permission_mode=data.get("claude", {}).get("permission_mode", "bypassPermissions"),
            claude_runner=data.get("claude", {}).get("runner", "oneshot"),
            claude_worker_idle_ttl_seconds=data.get("claude", {}).get("worker_idle_ttl_seconds", 900),
            claude_max_workers=data.get("claude", {}).get("max_workers", 3),
            claude_persistent_enabled_chats=data.get("claude", {}).get("persistent_enabled_chats", []),
            whisper_model=data.get("whisper", {}).get("model", "base"),
            whisper_load_policy=data.get("whisper", {}).get("load_policy", "preload"),
            bridge_data_dir=data.get("bridge", {}).get("data_dir", "./data"),
            bridge_log_level=data.get("bridge", {}).get("log_level", "INFO"),
            bridge_max_upload_mb=data.get("bridge", {}).get("max_upload_mb", 20),
            bridge_require_mention_in_group=data.get("bridge", {}).get("require_mention_in_group", True),
            bridge_bot_display_name=data.get("bridge", {}).get("bot_display_name", ""),
            bridge_personal_permission_profile=data.get("bridge", {}).get("personal_permission_profile", "admin"),
            bridge_bot_owner_id=data.get("bridge", {}).get("bot_owner_id", ""),
            bridge_bot_admins=data.get("bridge", {}).get("bot_admins", []),
            bridge_ws_profile=data.get("bridge", {}).get("ws_profile", "qiao-test"),
            bridge_ws_watchdog_interval_seconds=data.get("bridge", {}).get("ws_watchdog_interval_seconds", 30),
            bridge_ws_max_restart_failures=data.get("bridge", {}).get("ws_max_restart_failures", 3),
            bridge_console_message_log=data.get("bridge", {}).get("console_message_log", True),
            bridge_console_claude_stream=data.get("bridge", {}).get("console_claude_stream", True),
            bridge_queue_notice_after_seconds=data.get("bridge", {}).get("queue_notice_after_seconds", 8),
            bridge_media_batch_window_seconds=data.get("bridge", {}).get("media_batch_window_seconds", 10),
            bridge_message_coalesce_window_seconds=data.get("bridge", {}).get("message_coalesce_window_seconds", 10),
            bridge_text_coalesce_window_seconds=data.get("bridge", {}).get("text_coalesce_window_seconds", 2),
            bridge_progress_cards=data.get("bridge", {}).get("progress_cards", False),
            bridge_fast_tasks_enabled=data.get("bridge", {}).get("fast_tasks_enabled", True),
            bridge_local_tools=_load_local_tools(data.get("local_tools", [])),
            security_allowed_paths=data.get("security", {}).get("allowed_paths", []),
            security_blocked_keywords=data.get("security", {}).get("blocked_keywords", []),
        )

    return _env_override(cfg)


def _load_local_tools(data: Any) -> list[LocalToolConfig]:
    if not isinstance(data, list):
        return []
    tools: list[LocalToolConfig] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        tools.append(
            LocalToolConfig(
                name=name,
                enabled=bool(item.get("enabled", True)),
                keywords=[str(value) for value in item.get("keywords", [])],
                match_patterns=[str(value) for value in item.get("match_patterns", [])],
                command=[str(value) for value in item.get("command", [])],
                cwd=str(item.get("cwd", ".")),
                timeout_seconds=int(item.get("timeout_seconds", 180)),
                attachment_path_fields=[str(value) for value in item.get("attachment_path_fields", ["attachment_path", "file_path", "excelFilePath", "excel_path"])],
                summary_fields=[str(value) for value in item.get("summary_fields", ["summary", "message", "text"])],
                context_label=str(item.get("context_label", "local tool result")),
                prompt_hint=str(item.get("prompt_hint", "")),
            )
        )
    return tools
