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
    assert "<chat_memory>" in result
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


def test_rollover_updates_chat_memory_and_injects_it_next_turn(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:c1", "old_sid")
    bridge.session_store.record_turn("chat:c1", 10, 20)
    calls = []

    def fake_call(prompt, sid, **kwargs):
        calls.append((prompt, sid))
        if "交接摘要" in prompt or "handoff" in prompt.lower():
            return ("当前段摘要：用户偏好BI物流码表格。", sid)
        return ("滚动长期记忆：该 chat 主要处理 BI 物流码查询，偏好直接上传 Excel。", sid)

    monkeypatch.setattr(bridge, "_call_claude", fake_call)

    rule = resolve_rule({})
    bridge._maybe_rollover_session("chat:c1", rule, force=True)
    meta = bridge.session_store.get("chat:c1")
    prompt = bridge._build_prompt(
        "c1",
        "tester",
        bridge._memory_context_for_prompt("chat:c1", rule) + "\n\n继续查询",
        rule,
    )

    assert meta.memory["rolling_summary"]
    assert meta.memory_history
    assert "<chat_memory>" in prompt
    assert "BI物流码" in prompt


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


def test_short_text_on_heavy_session_uses_light_session_without_overwriting_work_session(tmp_path, monkeypatch):
    import json

    bridge = make_bridge(tmp_path)
    bridge.session_store.archive_and_rollover(
        "chat:oc_1",
        "old summary",
        "old_sid",
        rolling_summary="这个对话经常处理 BI、Excel、表格和物流码。",
    )
    bridge.session_store.update_session_id("chat:oc_1", "work_sid")
    bridge.session_store.record_turn("chat:oc_1", 25_000, 100)
    calls = []
    sent = []

    def fake_call(prompt, sid, **kwargs):
        calls.append(sid)
        return ("light reply", "light_sid")

    monkeypatch.setattr(bridge, "_call_claude", fake_call)
    monkeypatch.setattr(bridge, "_send_reply", lambda chat_id, content, msg_type="text": sent.append(content) or True)

    event = {
        "event": {
            "sender": {"sender_id": {"user_id": "ou_1", "name": "tester"}},
            "message": {
                "chat_id": "oc_1",
                "chat_type": "p2p",
                "content": json.dumps({"text": "现在速度怎么样"}),
                "message_id": "om_light",
                "message_type": "text",
            },
        }
    }

    bridge._process_event_body(event)

    assert calls == [None]
    assert "light reply" in sent[-1]
    assert bridge.session_store.get("chat:oc_1").session_id == "work_sid"


def test_context_decision_audit_records_prompt_size_and_strategy(tmp_path, monkeypatch, caplog):
    import json
    import logging

    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:oc_1", "work_sid")
    bridge.session_store.record_turn("chat:oc_1", 25_000, 100)
    sent = []

    monkeypatch.setattr(bridge, "_call_claude", lambda prompt, sid, **kwargs: ("ok", "light_sid"))
    monkeypatch.setattr(bridge, "_send_reply", lambda chat_id, content, msg_type="text": sent.append(content) or True)

    event = {
        "event": {
            "sender": {"sender_id": {"user_id": "ou_1", "name": "tester"}},
            "message": {
                "chat_id": "oc_1",
                "chat_type": "p2p",
                "content": json.dumps({"text": "现在速度怎么样"}),
                "message_id": "om_audit",
                "message_type": "text",
            },
        }
    }

    caplog.set_level(logging.INFO, logger="feishu_qiao.bridge")
    bridge._process_event_body(event)

    records = [
        json.loads(line)
        for line in (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decision = [record for record in records if record.get("action") == "context_decision"][-1]
    assert decision["strategy"] == "light"
    assert decision["prompt_chars"] > 0
    assert "memory_context_chars" in decision
    assert decision["resumed"] is False
    assert "Claude runtime: key=chat:oc_1" in caplog.text


def test_call_claude_with_recovery_retries_transient_500(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []

    def fake_call(prompt, sid, **kwargs):
        calls.append(sid)
        if len(calls) == 1:
            return ("API Error: 500 500 Internal Server Error", sid)
        return ("ok", "sid_1")

    monkeypatch.setattr(bridge, "_call_claude", fake_call)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    reply, new_session = bridge._call_claude_with_recovery(
        "prompt",
        "sid_1",
        "chat:c1",
        resolve_rule({}),
        cwd=str(tmp_path),
        permission_mode="bypassPermissions",
    )

    assert calls == ["sid_1", "sid_1"]
    assert reply == "ok"
    assert new_session == "sid_1"


def test_call_claude_with_recovery_rolls_over_on_context_limit(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:c1", "sid_old")
    calls = []
    rollovers = []

    def fake_call(prompt, sid, **kwargs):
        calls.append((prompt, sid))
        if len(calls) == 1:
            return ("context length exceeded", sid)
        return ("after rollover", "sid_new")

    def fake_rollover(session_key, rule, force=False):
        rollovers.append((session_key, force))
        bridge.session_store.clear_session_id(session_key)
        return "<chat_memory>memory</chat_memory>"

    monkeypatch.setattr(bridge, "_call_claude", fake_call)
    monkeypatch.setattr(bridge, "_maybe_rollover_session", fake_rollover)

    reply, new_session = bridge._call_claude_with_recovery(
        "prompt",
        "sid_old",
        "chat:c1",
        resolve_rule({}),
        cwd=str(tmp_path),
        permission_mode="bypassPermissions",
    )

    assert rollovers == [("chat:c1", True)]
    assert calls[1][1] is None
    assert "<chat_memory>memory</chat_memory>" in calls[1][0]
    assert reply == "after rollover"
    assert new_session == "sid_new"
