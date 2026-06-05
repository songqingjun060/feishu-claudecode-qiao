from datetime import datetime, timezone, timedelta

from feishu_claudecode_qiao.session_store import SessionStore, calculate_rollover_score, is_rollover_cooled_down, SessionMeta


def test_save_and_load(tmp_path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.update_session_id("chat:c1", "sess_123")
    store.record_turn("chat:c1", 10, 20)

    store2 = SessionStore(path)
    store2.load()
    meta = store2.get("chat:c1")
    assert meta.session_id == "sess_123"
    assert meta.message_count == 1
    assert meta.input_chars == 10


def test_archive_and_rollover(tmp_path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.update_session_id("chat:c1", "sess_old")
    store.record_turn("chat:c1", 100, 200)

    meta = store.archive_and_rollover("chat:c1", "summary text", "sess_old")
    assert meta.summary == "summary text"
    assert meta.rollover_count == 1
    assert meta.message_count == 0
    assert meta.session_id == ""


def test_clear_session(tmp_path):
    path = tmp_path / "sessions.json"
    store = SessionStore(path)
    store.update_session_id("chat:c1", "sess_123")
    store.clear_session("chat:c1")
    meta = store.get("chat:c1")
    assert meta.session_id == ""


def test_calculate_rollover_score_low():
    meta = SessionMeta(session_key="k")
    meta.message_count = 5
    score = calculate_rollover_score(meta, {})
    assert score < 100


def test_calculate_rollover_score_hard_limit():
    meta = SessionMeta(session_key="k")
    meta.message_count = 40
    meta.input_chars = 50000
    meta.output_chars = 100000
    score = calculate_rollover_score(meta, {})
    assert score >= 100


def test_calculate_rollover_score_context_error():
    meta = SessionMeta(session_key="k")
    score = calculate_rollover_score(meta, {}, context_error=True)
    assert score >= 100


def test_calculate_rollover_score_force():
    meta = SessionMeta(session_key="k")
    score = calculate_rollover_score(meta, {}, force=True)
    assert score >= 100


def test_is_rollover_cooled_down_no_history():
    meta = SessionMeta(session_key="k")
    assert is_rollover_cooled_down(meta, {}) is True


def test_is_rollover_cooled_down_recent():
    meta = SessionMeta(session_key="k")
    meta.last_rollover_at = datetime.now(timezone.utc).isoformat()
    meta.message_count = 10
    assert is_rollover_cooled_down(meta, {"rollover_cooldown_hours": 2}) is False
