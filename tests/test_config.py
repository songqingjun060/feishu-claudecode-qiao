import os
import pytest
from pathlib import Path
from feishu_claudecode_qiao.config import load_config, Config


def test_config_defaults():
    config = Config()
    assert config.feishu_app_id == ""
    assert config.feishu_domain == "https://open.feishu.cn"
    assert config.bridge_log_level == "INFO"
    assert config.feishu_gateway_backend == "current"
    assert config.feishu_event_backend == "start_ws"
    assert config.bridge_console_message_log is True
    assert config.bridge_console_claude_stream is True
    assert config.whisper_load_policy == "preload"
    assert config.bridge_local_tools == []


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_APP_ID", "from_env")
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_GATEWAY_BACKEND", "lark_oapi")
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_EVENT_BACKEND", "lark_oapi_ws")
    monkeypatch.setenv("FEISHUCLAUDECODE_BRIDGE_CONSOLE_MESSAGE_LOG", "false")
    monkeypatch.setenv("FEISHUCLAUDECODE_BRIDGE_CONSOLE_CLAUDE_STREAM", "false")
    monkeypatch.setenv("FEISHUCLAUDECODE_WHISPER_LOAD_POLICY", "per_call")
    config = load_config()
    assert config.feishu_app_id == "from_env"
    assert config.feishu_gateway_backend == "lark_oapi"
    assert config.feishu_event_backend == "lark_oapi_ws"
    assert config.bridge_console_message_log is False
    assert config.bridge_console_claude_stream is False
    assert config.whisper_load_policy == "per_call"


def test_config_reads_explicit_backend_selection(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[feishu]
gateway_backend = "lark_oapi"
event_backend = "lark_oapi_ws"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.feishu_gateway_backend == "lark_oapi"
    assert config.feishu_event_backend == "lark_oapi_ws"


def test_load_agent_bridge_upgrade_options(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[claude]
runner = "oneshot"
worker_idle_ttl_seconds = 900
max_workers = 3
persistent_enabled_chats = ["oc_1", "oc_2"]

[bridge]
queue_notice_after_seconds = 6
media_batch_window_seconds = 4
text_coalesce_window_seconds = 1
progress_cards = true
fast_tasks_enabled = false

[[local_tools]]
name = "sample_lookup"
keywords = ["查询"]
match_patterns = ["\\\\b[A-Z]{2}\\\\d{4}\\\\b"]
command = ["sample.exe", "--ids", "{matches}"]
cwd = "D:/tools/sample"
timeout_seconds = 30
health_command = ["sample.exe", "--health"]
health_interval_seconds = 900
health_startup_delay_seconds = 15
health_timeout_seconds = 12
refresh_command = ["sample.exe", "--refresh-auth"]
refresh_timeout_seconds = 120
refresh_cooldown_seconds = 1800
context_label = "sample lookup"
prompt_hint = "Extract every code from recent images or files, then call this tool."
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.claude_runner == "oneshot"
    assert config.claude_worker_idle_ttl_seconds == 900
    assert config.claude_max_workers == 3
    assert config.claude_persistent_enabled_chats == ["oc_1", "oc_2"]
    assert config.bridge_queue_notice_after_seconds == 6
    assert config.bridge_media_batch_window_seconds == 4
    assert config.bridge_text_coalesce_window_seconds == 1
    assert config.bridge_progress_cards is True
    assert config.bridge_fast_tasks_enabled is False
    assert len(config.bridge_local_tools) == 1
    tool = config.bridge_local_tools[0]
    assert tool.name == "sample_lookup"
    assert tool.keywords == ["查询"]
    assert tool.match_patterns == ["\\b[A-Z]{2}\\d{4}\\b"]
    assert tool.command == ["sample.exe", "--ids", "{matches}"]
    assert tool.cwd == "D:/tools/sample"
    assert tool.timeout_seconds == 30
    assert tool.health_command == ["sample.exe", "--health"]
    assert tool.health_interval_seconds == 900
    assert tool.health_startup_delay_seconds == 15
    assert tool.health_timeout_seconds == 12
    assert tool.refresh_command == ["sample.exe", "--refresh-auth"]
    assert tool.refresh_timeout_seconds == 120
    assert tool.refresh_cooldown_seconds == 1800
    assert tool.context_label == "sample lookup"
    assert tool.prompt_hint == "Extract every code from recent images or files, then call this tool."
