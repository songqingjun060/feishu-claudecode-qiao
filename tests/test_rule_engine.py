from feishu_claudecode_qiao.rule_engine import (
    deep_merge,
    resolve_rule,
    validate_rule,
    build_session_key,
    DEFAULT_RULE,
)


def test_deep_merge_override_scalar():
    base = {"a": 1, "b": {"x": 10}}
    override = {"a": 2}
    result = deep_merge(base, override)
    assert result["a"] == 2
    assert result["b"]["x"] == 10


def test_deep_merge_nested_dict():
    base = {"b": {"x": 10, "y": 20}}
    override = {"b": {"x": 99}}
    result = deep_merge(base, override)
    assert result["b"]["x"] == 99
    assert result["b"]["y"] == 20


def test_resolve_rule_default():
    rule = resolve_rule({})
    assert rule.get("session_mode") == "shared_chat"
    assert rule.get("permission_profile") == "safe"


def test_resolve_rule_chat_override():
    rule = resolve_rule({"session_mode": "per_user"})
    assert rule.get("session_mode") == "per_user"
    assert "chat" in rule.source


def test_resolve_rule_member_override():
    chat_rule = {
        "custom_prompt": "chat_prompt",
        "members": {
            "user_a": {"custom_prompt": "user_a_prompt"}
        }
    }
    rule = resolve_rule(chat_rule, sender_id="user_a")
    assert rule.get("custom_prompt") == "user_a_prompt"
    assert "member:user_a" in rule.source


def test_resolve_rule_temporary_override():
    rule = resolve_rule({"session_mode": "shared_chat"}, temporary={"session_mode": "stateless"})
    assert rule.get("session_mode") == "stateless"


def test_validate_rule_invalid_session_mode():
    errors = validate_rule({"session_mode": "invalid_mode"})
    assert any("session_mode" in e for e in errors)


def test_validate_rule_invalid_permission_profile():
    errors = validate_rule({"permission_profile": "hacker"})
    assert any("permission_profile" in e for e in errors)


def test_build_session_key_shared_chat():
    assert build_session_key("c1", "u1", "shared_chat") == "chat:c1"


def test_build_session_key_per_user():
    assert build_session_key("c1", "u1", "per_user") == "chat:c1:user:u1"


def test_build_session_key_stateless():
    assert build_session_key("c1", "u1", "stateless") is None


def test_permission_mode_for_profile_safe_is_not_bypass():
    from feishu_claudecode_qiao.rule_engine import permission_mode_for_profile
    assert permission_mode_for_profile("safe") != "bypassPermissions"


def test_permission_mode_for_profile_admin_is_bypass():
    from feishu_claudecode_qiao.rule_engine import permission_mode_for_profile
    assert permission_mode_for_profile("admin") == "bypassPermissions"


def test_permission_mode_for_profile_mapping():
    from feishu_claudecode_qiao.rule_engine import permission_mode_for_profile
    assert permission_mode_for_profile("readonly") == "default"
    assert permission_mode_for_profile("dev") == "acceptEdits"
    assert permission_mode_for_profile("stateless") == "default"
    assert permission_mode_for_profile("") == "default"
    assert permission_mode_for_profile("unknown", fallback="safe") == "safe"
