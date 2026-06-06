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


def test_build_prompt_includes_security_boundary_with_allowed_paths(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        claude_work_dir="D:/default-work",
        security_allowed_paths=["D:/shared"],
    ))
    rule = resolve_rule({
        "workspace": "D:/project-a",
        "allowed_paths": ["D:/project-a/data"],
    })

    prompt = bridge._build_prompt("chat_a", "张三", "你能访问哪些文件？", rule)

    assert "<bridge_security_boundary>" in prompt
    assert "Current chat workspace:" in prompt
    assert "D:/project-a" in prompt
    assert "D:/shared" in prompt
    assert "D:/project-a/data" in prompt
    assert "only local paths the user has authorized" in prompt
    assert "Do not claim or imply access to other local directories" in prompt


def test_build_prompt_uses_default_workspace_in_security_boundary(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        claude_work_dir="D:/default-work",
    ))
    rule = resolve_rule({})

    prompt = bridge._build_prompt("chat_a", "张三", "workspace?", rule)

    assert "Current chat workspace:" in prompt
    assert "D:/default-work" in prompt
    assert "User-authorized allowed_paths for this chat:\n- (none)" in prompt
