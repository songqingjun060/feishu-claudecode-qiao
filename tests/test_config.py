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


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_APP_ID", "from_env")
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_GATEWAY_BACKEND", "lark_oapi")
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_EVENT_BACKEND", "lark_oapi_ws")
    monkeypatch.setenv("FEISHUCLAUDECODE_BRIDGE_CONSOLE_MESSAGE_LOG", "false")
    monkeypatch.setenv("FEISHUCLAUDECODE_BRIDGE_CONSOLE_CLAUDE_STREAM", "false")
    config = load_config()
    assert config.feishu_app_id == "from_env"
    assert config.feishu_gateway_backend == "lark_oapi"
    assert config.feishu_event_backend == "lark_oapi_ws"
    assert config.bridge_console_message_log is False
    assert config.bridge_console_claude_stream is False


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
