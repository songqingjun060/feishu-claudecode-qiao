import json

from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def make_bridge(tmp_path, base_url):
    return Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            vision_api_key="sk-test",
            vision_base_url=base_url,
            vision_model="kimi-for-coding",
        )
    )


def test_kimi_coding_base_uses_anthropic_messages_endpoint(tmp_path):
    bridge = make_bridge(tmp_path, "https://api.kimi.com/coding/")

    assert bridge._vision_api_format() == "anthropic"
    assert bridge._vision_api_url("anthropic") == "https://api.kimi.com/coding/v1/messages"


def test_openai_compatible_base_does_not_duplicate_v1(tmp_path):
    bridge = make_bridge(tmp_path, "https://api.kimi.com/coding/v1")

    assert bridge._vision_api_format() == "openai"
    assert bridge._vision_api_url("openai") == "https://api.kimi.com/coding/v1/chat/completions"


def test_openai_compatible_full_endpoint_is_preserved(tmp_path):
    bridge = make_bridge(tmp_path, "https://api.kimi.com/coding/v1/chat/completions")

    assert bridge._vision_api_url("openai") == "https://api.kimi.com/coding/v1/chat/completions"
