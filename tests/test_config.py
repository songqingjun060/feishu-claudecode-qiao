import os
import pytest
from pathlib import Path
from feishu_claudecode_qiao.config import load_config, Config


def test_config_defaults():
    config = Config()
    assert config.feishu_app_id == ""
    assert config.feishu_domain == "https://open.feishu.cn"
    assert config.bridge_log_level == "INFO"


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("FEISHUCLAUDECODE_FEISHU_APP_ID", "from_env")
    config = load_config()
    assert config.feishu_app_id == "from_env"
