import json

import start_ws

from feishu_claudecode_qiao.claude_runner import (
    ClaudeRunRequest,
    PersistentClaudeRunner,
)
from feishu_claudecode_qiao.config import Config
from feishu_claudecode_qiao.rule_engine import DEFAULT_RULE
from feishu_claudecode_qiao.security import SecurityPolicy
from feishu_claudecode_qiao.session_store import SessionMeta
from feishu_claudecode_qiao.session_strategy import (
    choose_session_strategy,
    should_force_rollover_after_timing,
)


def test_default_whisper_policy_preloads_model():
    assert Config().whisper_load_policy == "preload"


def test_default_soul_uses_readable_simplified_chinese():
    soul = DEFAULT_RULE["soul"]
    assert soul["role"] == "当前飞书对话框里的 Claude Code 协作助手"
    assert "简体中文" in soul["output_style"]
    assert "鈿" not in str(soul)
    assert "鐗" not in str(soul)


def test_security_warning_and_risky_intent_use_readable_chinese():
    policy = SecurityPolicy(blocked_keywords=["敏感词"])

    blocked, warning = policy.check_message("这里包含敏感词")
    shell = policy.check_risky_intent("请执行 powershell 命令")
    move = policy.check_risky_intent("把文件移动到 D:/backup")

    assert blocked is True
    assert "消息已被拦截" in warning
    assert "敏感关键词" in warning
    assert shell.risky is True
    assert shell.category == "shell"
    assert "危险" in shell.reason
    assert move.risky is True
    assert move.category == "move"


def test_chinese_work_intent_uses_work_strategy_for_heavy_session():
    meta = SessionMeta(session_key="chat:c1", session_id="sid_old")
    meta.input_chars = 50000
    meta.message_count = 20

    decision = choose_session_strategy(
        "帮我分析刚才的图片并生成表格",
        msg_type="text",
        session_meta=meta,
        effective_rule={},
    )

    assert decision.strategy == "work"
    assert decision.session_id == "sid_old"


def test_slow_claude_timing_no_longer_forces_rollover():
    assert not should_force_rollover_after_timing(
        prompt_built_to_claude_completed_ms=35_000,
        threshold_ms=30_000,
    )


class FakeSDKClient:
    created = []

    def __init__(self, *, options):
        self.options = options
        self.queries = []
        FakeSDKClient.created.append(self)

    async def connect(self):
        return None

    async def query(self, prompt):
        self.queries.append(prompt)

    def receive_response(self):
        async def iterator():
            yield {"type": "system", "session_id": "sid_sdk"}
            yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}

        return iterator()

    async def disconnect(self):
        return None


class FakeSDKOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_persistent_runner_does_not_reinject_equivalent_startup_prompt():
    FakeSDKClient.created = []
    runner = PersistentClaudeRunner(
        client_cls=FakeSDKClient,
        options_cls=FakeSDKOptions,
        now=lambda: 100.0,
    )

    runner.run(ClaudeRunRequest(prompt="one", session_key="chat:1", startup_prompt="soul\n\nrules"))
    result = runner.run(ClaudeRunRequest(prompt="two", session_key="chat:1", startup_prompt="soul\nrules"))
    stats = runner.stats()

    assert result.reused_worker is True
    assert result.startup_injected is False
    assert FakeSDKClient.created[0].queries == ["soul\n\nrules", "one", "two"]
    assert stats["workers"][0]["startup_hash"]


def test_start_ws_subscribes_reaction_events_for_quiet_handlers():
    assert "im.message.receive_v1" in start_ws.EVENT_TYPES
    assert "im.message.reaction.created_v1" in start_ws.EVENT_TYPES
    assert "im.message.reaction.deleted_v1" in start_ws.EVENT_TYPES


def test_context_decision_records_message_id(tmp_path, monkeypatch):
    from feishu_claudecode_qiao.bridge import Bridge
    from feishu_claudecode_qiao.config import Config

    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
        )
    )
    bridge.session_store.update_session_id("chat:oc_1", "work_sid")
    bridge.session_store.record_turn("chat:oc_1", 25_000, 100)

    monkeypatch.setattr(bridge, "_call_claude", lambda prompt, sid, **kwargs: ("ok", "light_sid"))
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

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

    bridge._process_event_body(event)

    records = [
        json.loads(line)
        for line in (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    decision = [record for record in records if record.get("action") == "context_decision"][-1]
    assert decision["message_id"] == "om_audit"


def test_reaction_events_are_not_dispatched_as_messages(tmp_path, monkeypatch):
    from feishu_claudecode_qiao.bridge import Bridge
    from feishu_claudecode_qiao.config import Config

    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
        )
    )
    dispatched = []
    monkeypatch.setattr(bridge.event_dispatcher, "dispatch", dispatched.append)

    event = bridge._normalize_event(
        {
            "action": "added",
            "action_time": "1781831542112",
            "emoji_type": "OK",
            "event_id": "evt_reaction",
            "message_id": "om_source",
            "timestamp": "1781831542112",
            "type": "im.message.reaction.created_v1",
        }
    )

    bridge._dispatch_event(event)

    assert dispatched == []
