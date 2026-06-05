import pytest
from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config
from feishu_claudecode_qiao.rule_engine import resolve_rule


def make_bridge(tmp_path):
    return Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
    ))


def test_maybe_rollover_low_score_does_nothing(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    called = False
    def fake_call(prompt, sid, **kwargs):
        nonlocal called
        called = True
        return ("summary", "new_sess")
    monkeypatch.setattr(bridge, "_call_claude", fake_call)
    rule = resolve_rule({})
    result = bridge._maybe_rollover_session("chat:c1", rule)
    assert not called
    assert result == ""


def test_maybe_rollover_force_triggers_call(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    called = False
    def fake_call(prompt, sid, **kwargs):
        nonlocal called
        called = True
        return ("summary text", "new_sess")
    monkeypatch.setattr(bridge, "_call_claude", fake_call)
    bridge.session_store.update_session_id("chat:c1", "sess_old")
    bridge.session_store.record_turn("chat:c1", 10, 20)
    rule = resolve_rule({})
    result = bridge._maybe_rollover_session("chat:c1", rule, force=True)
    assert called
    assert "交接摘要" in result
    assert "summary text" in result


def test_rollover_current_message_uses_new_session_and_carries_summary(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:c1", "old_sid")
    bridge.session_store.record_turn("chat:c1", 10, 20)

    calls = []

    def fake_call(prompt, sid, **kwargs):
        calls.append((prompt, sid))
        if "请为下一段 Claude Code 会话生成交接摘要" in prompt:
            return ("handoff summary", sid)
        return ("final reply", "new_sid")

    monkeypatch.setattr(bridge, "_call_claude", fake_call)

    rule = resolve_rule({})
    rollover_summary = bridge._maybe_rollover_session("chat:c1", rule, force=True)
    prompt = bridge._build_prompt("c1", "张三", rollover_summary + "\n\n继续任务", rule)
    reply, new_session = bridge._call_claude(prompt, bridge.session_store.get("chat:c1").session_id or None)

    assert calls[0][1] == "old_sid"
    assert calls[1][1] in ("", None)
    assert "handoff summary" in calls[1][0]
    assert reply == "final reply"
    assert new_session == "new_sid"


def test_process_event_retries_when_saved_claude_session_is_missing(tmp_path, monkeypatch):
    import json

    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:oc_1", "missing_sid")
    calls = []
    sent = []

    def fake_call(prompt, sid, **kwargs):
        calls.append(sid)
        if sid == "missing_sid":
            return ("[错误: Claude session 不存在: missing_sid]", None)
        return ("final reply", "new_sid")

    monkeypatch.setattr(bridge, "_call_claude", fake_call)
    monkeypatch.setattr(bridge, "_send_reply", lambda chat_id, content, msg_type="text": sent.append(content) or True)

    event = {
        "event": {
            "sender": {"sender_id": {"user_id": "ou_1", "name": "tester"}},
            "message": {
                "chat_id": "oc_1",
                "chat_type": "p2p",
                "content": json.dumps({"text": "hello"}),
                "message_id": "om_1",
                "message_type": "text",
            },
        }
    }

    bridge._process_event_body(event)

    assert calls == ["missing_sid", None]
    assert "final reply" in sent[-1]
    assert bridge.session_store.get("chat:oc_1").session_id == "new_sid"
