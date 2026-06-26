from feishu_claudecode_qiao.session_store import SessionMeta
from feishu_claudecode_qiao.session_strategy import (
    choose_session_strategy,
    should_force_rollover_after_timing,
)


def test_short_plain_message_resumes_work_session_when_session_is_heavy():
    meta = SessionMeta(session_key="chat:c1", session_id="sid_old")
    meta.input_chars = 25000
    meta.message_count = 20

    decision = choose_session_strategy(
        "现在速度怎么样",
        msg_type="text",
        session_meta=meta,
        effective_rule={},
    )

    assert decision.strategy == "work"
    assert decision.session_id == "sid_old"
    assert decision.remember_turn is True
    assert decision.reason == "default_work"


def test_file_or_path_message_uses_work_strategy_and_resumes_session():
    meta = SessionMeta(session_key="chat:c1", session_id="sid_old")

    decision = choose_session_strategy(
        "读取 D:/data/report.xlsx 并生成表格",
        msg_type="text",
        session_meta=meta,
        effective_rule={},
    )

    assert decision.strategy == "work"
    assert decision.session_id == "sid_old"
    assert decision.remember_turn is True


def test_explicit_fresh_request_drops_saved_session_but_keeps_memory():
    meta = SessionMeta(session_key="chat:c1", session_id="sid_old")

    decision = choose_session_strategy(
        "/new 测试连接",
        msg_type="text",
        session_meta=meta,
        effective_rule={},
    )

    assert decision.strategy == "fresh"
    assert decision.session_id is None
    assert decision.remember_turn is True


def test_rule_can_force_work_strategy():
    meta = SessionMeta(session_key="chat:c1", session_id="sid_old")
    meta.input_chars = 50000

    decision = choose_session_strategy(
        "简单问候",
        msg_type="text",
        session_meta=meta,
        effective_rule={"session_strategy": {"mode": "work"}},
    )

    assert decision.strategy == "work"
    assert decision.session_id == "sid_old"


def test_slow_claude_timing_does_not_force_rollover():
    assert not should_force_rollover_after_timing(
        prompt_built_to_claude_completed_ms=35_000,
        threshold_ms=30_000,
    )
    assert not should_force_rollover_after_timing(
        prompt_built_to_claude_completed_ms=8_000,
        threshold_ms=30_000,
    )
