import pytest
from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def make_bridge(tmp_path):
    return Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
    ))


def test_cmd_help(tmp_path):
    bridge = make_bridge(tmp_path)
    reply = bridge._cmd_help()
    assert "/help" in reply
    assert "/rules" in reply


def test_cmd_rules(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({"session_mode": "per_user"})
    reply = bridge._cmd_rules(rule)
    assert "per_user" in reply


def test_cmd_context_no_session_key(tmp_path):
    bridge = make_bridge(tmp_path)
    reply = bridge._cmd_context(None)
    assert "无状态" in reply


def test_cmd_context_with_session_key(tmp_path):
    bridge = make_bridge(tmp_path)
    reply = bridge._cmd_context("chat:c1")
    assert "chat:c1" in reply


def test_cmd_summary_no_session_key(tmp_path):
    bridge = make_bridge(tmp_path)
    reply = bridge._cmd_summary(None)
    assert "无会话摘要" in reply


def test_cmd_summary_empty(tmp_path):
    bridge = make_bridge(tmp_path)
    reply = bridge._cmd_summary("chat:c1")
    assert "没有保存" in reply


def test_parse_memory_command():
    from feishu_claudecode_qiao.commands import parse_command
    cmd = parse_command("/memory history")
    assert cmd.is_command
    assert cmd.name == "memory"
    assert cmd.args == "history"


def test_cmd_memory_show_and_clear(tmp_path):
    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:c1", "sess_1")
    bridge.session_store.archive_and_rollover(
        "chat:c1",
        "segment summary",
        "sess_1",
        rolling_summary="chat role memory",
    )
    bridge.session_store.update_session_id("chat:c1", "sess_2")

    reply = bridge._cmd_memory("chat:c1", "")
    assert "chat role memory" in reply

    reply = bridge._cmd_memory("chat:c1", "clear")
    assert "清空" in reply
    meta = bridge.session_store.get("chat:c1")
    assert meta.session_id == "sess_2"
    assert meta.memory["rolling_summary"] == ""


def test_cmd_workspace_show(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({"workspace": str(tmp_path)})
    reply = bridge._cmd_workspace("c1", "", rule)
    assert str(tmp_path) in reply


def test_cmd_permission_show(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({"permission_profile": "dev"})
    reply = bridge._cmd_permission("c1", "", rule)
    assert "dev" in reply
    assert "开发" in reply


def test_cmd_workspace_set_and_clear(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    ws = tmp_path / "ws"
    ws.mkdir()
    reply = bridge._cmd_workspace("c1", f"set {ws}", resolve_rule({}))
    assert "已设置" in reply
    assert str(ws) in reply
    assert bridge.chat_rules.get("c1")["allowed_paths"] == [str(ws.resolve())]
    reply = bridge._cmd_workspace("c1", "clear", resolve_rule({}))
    assert "已清空" in reply


def test_cmd_workspace_set_rejects_system_path(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    reply = bridge._cmd_workspace(
        "c1",
        "set C:/Windows/System32",
        resolve_rule({}),
    )
    assert "拒绝" in reply or "不允许" in reply


def test_cmd_workspace_set_rejects_missing_path(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    missing = tmp_path / "missing"
    reply = bridge._cmd_workspace(
        "c1",
        f"set {missing}",
        resolve_rule({}),
    )
    assert "不存在" in reply


def test_group_member_without_bot_admin_cannot_set_workspace(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({})
    assert bridge._can_modify_chat_rule(rule, "u1", "group") is False


def test_group_bot_admin_can_set_workspace(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        bridge_bot_admins=["u1"],
    ))
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({}, sender_id="u1")
    assert bridge._can_modify_chat_rule(rule, "u1", "group") is True


def test_group_bot_owner_can_manage_when_admins_not_configured(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        bridge_bot_owner_id="owner_1",
    ))
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({}, sender_id="owner_1")
    assert bridge._can_modify_chat_rule(rule, "owner_1", "group") is True
    assert bridge._can_modify_chat_rule(rule, "u1", "group") is False


def test_group_rule_admin_no_longer_grants_bot_rule_management(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({"rule_admins": ["u1"]}, sender_id="u1")
    assert bridge._can_modify_chat_rule(rule, "u1", "group") is False


def test_private_chat_can_modify_rule(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    rule = resolve_rule({})
    assert bridge._can_modify_chat_rule(rule, "u1", "p2p") is True


def test_cmd_workspace_set_denied_for_group_member(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    ws = tmp_path / "ws"
    ws.mkdir()
    rule = resolve_rule({})
    reply = bridge._cmd_workspace(
        "c1", f"set {ws}", rule, can_modify=False,
    )
    assert "拒绝修改规则" in reply



def test_cmd_paths_adds_multiple_directories(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    reply = bridge._cmd_paths("c1", f"add {a}, {b}", resolve_rule({}))

    assert str(a.resolve()) in reply
    assert str(b.resolve()) in reply
    assert bridge.chat_rules.get("c1")["allowed_paths"] == [str(a.resolve()), str(b.resolve())]


def test_cmd_paths_ignores_trailing_bot_mention(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    target = tmp_path / "storage"
    target.mkdir()

    reply = bridge._cmd_paths("c1", f"add {target} @??", resolve_rule({}))

    assert str(target.resolve()) in reply
    assert "@??" not in bridge.chat_rules.get("c1")["allowed_paths"][0]


def test_cmd_workspace_ignores_trailing_bot_mention(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    target = tmp_path / "workspace"
    target.mkdir()

    reply = bridge._cmd_workspace("c1", f"set {target} @??", resolve_rule({}))

    assert str(target.resolve()) in reply
    assert bridge.chat_rules.get("c1")["workspace"] == str(target.resolve())


def test_natural_group_access_rule_maps_drive_to_paths_command(tmp_path):
    bridge = make_bridge(tmp_path)
    cmd = bridge._natural_rule_command("\u6b64\u7fa4\u8bbf\u95ee\u6743\u9650\u8bbe\u7f6e\u4e3aD\u76d8", "group")

    assert cmd is not None
    assert cmd.name == "paths"
    assert cmd.args == "add D:/"


def test_natural_group_permission_rule_maps_to_permission_command(tmp_path):
    bridge = make_bridge(tmp_path)
    cmd = bridge._natural_rule_command("\u6b64\u7fa4\u6743\u9650\u8bbe\u4e3aadmin", "group")

    assert cmd is not None
    assert cmd.name == "permission"
    assert cmd.args == "set admin"


def test_natural_group_approve_permission_maps_to_admin(tmp_path):
    bridge = make_bridge(tmp_path)
    cmd = bridge._natural_rule_command("\u6279\u51c6\u6743\u9650@\u6d4b\u8bd5", "group")

    assert cmd is not None
    assert cmd.name == "permission"
    assert cmd.args == "set admin"


def test_cmd_permission_set_returns_chinese_label(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule

    reply = bridge._cmd_permission("c1", "set admin", resolve_rule({}))

    assert "admin" in reply
    assert "最大权限" in reply


def test_cmd_rules_returns_chinese_permission_label(tmp_path):
    bridge = make_bridge(tmp_path)
    from feishu_claudecode_qiao.rule_engine import resolve_rule

    reply = bridge._cmd_rules(resolve_rule({"permission_profile": "admin"}))

    assert "admin" in reply
    assert "最大权限" in reply


def test_group_onboarding_mentions_paths_and_rules(tmp_path):
    bridge = make_bridge(tmp_path)
    reply = bridge._cmd_group_onboarding()

    assert "/rules" in reply
    assert "/paths add" in reply
    assert "/workspace set" in reply
