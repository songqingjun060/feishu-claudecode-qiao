from feishu_claudecode_qiao.chat_rules import ChatRules


def test_set_member(tmp_path):
    cr = ChatRules(str(tmp_path))
    cr.set_member("chat_1", "user_a", custom_prompt="hello")
    rule = cr.get("chat_1")
    assert rule["members"]["user_a"]["custom_prompt"] == "hello"


def test_delete_member(tmp_path):
    cr = ChatRules(str(tmp_path))
    cr.set_member("chat_1", "user_a", custom_prompt="hello")
    cr.delete_member("chat_1", "user_a")
    rule = cr.get("chat_1")
    assert "user_a" not in rule.get("members", {})


def test_get_returns_defaults(tmp_path):
    cr = ChatRules(str(tmp_path))
    rule = cr.get("new_chat")
    assert "workspace" in rule


def test_validate_invalid_session_mode(tmp_path):
    cr = ChatRules(str(tmp_path))
    cr.set("chat_1", session_mode="invalid_mode")
    errors = cr.validate("chat_1")
    assert any("session_mode" in e for e in errors)
