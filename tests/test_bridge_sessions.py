import json

from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config
from feishu_claudecode_qiao.rule_engine import build_session_key


def make_bridge(tmp_path):
    return Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
    ))


def test_session_key_shared_chat(tmp_path):
    key = build_session_key("c1", "u1", "shared_chat")
    assert key == "chat:c1"
    key2 = build_session_key("c1", "u2", "shared_chat")
    assert key2 == key


def test_session_key_per_user(tmp_path):
    key1 = build_session_key("c1", "u1", "per_user")
    key2 = build_session_key("c1", "u2", "per_user")
    assert key1 != key2


def test_session_key_stateless(tmp_path):
    key = build_session_key("c1", "u1", "stateless")
    assert key is None


def test_bridge_has_session_store(tmp_path):
    bridge = make_bridge(tmp_path)
    assert bridge.session_store is not None
    assert bridge.session_store.path == bridge.sessions_file


def test_bridge_save_sessions_does_not_overwrite_session_store(tmp_path):
    bridge = make_bridge(tmp_path)
    bridge.session_store.update_session_id("chat:c1", "sess_1")
    bridge.session_store.record_turn("chat:c1", 10, 20)

    bridge._save_sessions()

    data = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    assert "chat:c1" in data
    assert data["chat:c1"]["session_id"] == "sess_1"
    assert data["chat:c1"]["message_count"] == 1


def test_session_store_legacy_migration(tmp_path):
    # Write legacy format (key -> session_id string)
    legacy = {"chat:c1": "sess_legacy", "c2": "sess_legacy2"}
    (tmp_path / "sessions.json").write_text(json.dumps(legacy), encoding="utf-8")

    bridge = make_bridge(tmp_path)
    assert bridge.session_store.get("chat:c1").session_id == "sess_legacy"
    assert bridge.session_store.get("chat:c2").session_id == "sess_legacy2"
