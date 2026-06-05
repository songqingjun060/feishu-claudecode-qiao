from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config
from feishu_claudecode_qiao.rule_engine import resolve_rule


def make_bridge(tmp_path):
    return Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
    ))


def test_build_prompt_with_chat_custom_prompt(tmp_path):
    bridge = make_bridge(tmp_path)
    rule = resolve_rule({"custom_prompt": "chat_prompt"})
    prompt = bridge._build_prompt("c1", "张三", "hello", rule)
    assert "chat_prompt" in prompt


def test_build_prompt_with_workspace(tmp_path):
    bridge = make_bridge(tmp_path)
    rule = resolve_rule({"workspace": "D:/project"})
    prompt = bridge._build_prompt("c1", "张三", "hello", rule)
    assert "D:/project" in prompt
