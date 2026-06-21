import json
import os
import sys
from pathlib import Path

from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def test_bridge_paths_use_configured_data_dir(tmp_path):
    data_dir = tmp_path / "custom-data"
    bi_tool_dir = tmp_path / "bi-tool"
    config = Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(data_dir),
        bridge_bi_logistics_tool_dir=str(bi_tool_dir),
    )

    bridge = Bridge(config)

    assert bridge.data_dir == data_dir.resolve()
    assert bridge.pid_file == data_dir.resolve() / "bridge.pid"
    assert bridge.sessions_file == data_dir.resolve() / "sessions.json"
    assert bridge.ws_events_file == data_dir.resolve() / "logs" / "feishu_ws_events.jsonl"
    assert bridge.images_dir == data_dir.resolve() / "images"
    assert bridge.attachments_dir == data_dir.resolve() / "attachments"
    assert bridge.bi_logistics_runner.tool_dir == bi_tool_dir.resolve()


def test_websocket_watchdog_starts_subscriber_when_pid_missing(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_ws_profile="qiao-test",
        ),
        config_path=config_path,
    )
    calls = []

    monkeypatch.setattr(
        "feishu_claudecode_qiao.bridge.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs))
        or type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})(),
    )

    bridge._check_websocket_watchdog(force=True)

    assert calls
    args = calls[0][0]
    assert args[:3] == [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "start_ws.py"),
        "start",
    ]
    assert "--config" in args
    assert str(config_path) in args
    assert "--profile" in args
    assert "qiao-test" in args


def test_websocket_watchdog_exits_after_repeated_restart_failures(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_ws_profile="qiao-test",
            bridge_ws_max_restart_failures=2,
        ),
        config_path=config_path,
    )

    monkeypatch.setattr(
        "feishu_claudecode_qiao.bridge.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})(),
    )

    bridge._check_websocket_watchdog(force=True)
    try:
        bridge._check_websocket_watchdog(force=True)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("bridge should exit after repeated WebSocket restart failures")


def test_stop_managed_websocket_calls_start_ws_stop(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_ws_profile="qiao-test",
        ),
        config_path=config_path,
    )
    calls = []

    monkeypatch.setattr(
        "feishu_claudecode_qiao.bridge.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs))
        or type("Result", (), {"returncode": 0, "stdout": "stopped", "stderr": ""})(),
    )

    bridge._stop_managed_websocket()

    assert calls
    args = calls[0][0]
    assert args[:3] == [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "start_ws.py"),
        "stop",
    ]
    assert "--config" in args
    assert str(config_path) in args
    assert "--profile" in args
    assert "qiao-test" in args


def test_websocket_watchdog_does_not_start_when_pid_running(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    pid_file = tmp_path / "feishu_ws.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    (tmp_path / "feishu_ws.meta.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "profile": "qiao-test",
                "config_path": str(config_path.resolve()),
                "data_dir": str(tmp_path.resolve()),
            }
        ),
        encoding="utf-8",
    )
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_ws_profile="qiao-test",
        ),
        config_path=config_path,
    )
    calls = []

    monkeypatch.setattr(
        "feishu_claudecode_qiao.bridge.subprocess.run",
        lambda *args, **kwargs: calls.append(args),
    )

    bridge._check_websocket_watchdog(force=True)

    assert calls == []


def test_pid_helpers_use_given_path(tmp_path):
    from feishu_claudecode_qiao.bridge import _is_running, _write_pid, _remove_pid
    pid_file = tmp_path / "bridge.pid"
    assert not _is_running(pid_file)
    _write_pid(pid_file)
    assert _is_running(pid_file)
    _remove_pid(pid_file)
    assert not _is_running(pid_file)


def test_security_for_rule_uses_rule_workspace(tmp_path):
    from feishu_claudecode_qiao.rule_engine import resolve_rule
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        whisper_load_policy="lazy",
    ))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    rule = resolve_rule({"workspace": str(workspace)})
    security = bridge._security_for_rule(rule)
    assert security.is_path_allowed(workspace / "a.txt") is True
    assert security.is_path_allowed("C:/Windows/system32") is False


def make_text_event(chat_id, sender, text):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "m_path",
                "chat_type": "p2p",
                "chat_id": chat_id,
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        }
    }


def test_process_event_rejects_disallowed_path_before_claude(tmp_path, monkeypatch):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        whisper_load_policy="lazy",
    ))
    sent = []
    called = []

    monkeypatch.setattr(bridge, "_send_reply", lambda chat_id, content, msg_type="text": sent.append(content) or True)
    monkeypatch.setattr(bridge, "_call_claude", lambda *args, **kwargs: called.append(True) or ("reply", "sid"))

    bridge._process_event(make_text_event("c1", "u1", "请读取 C:/Windows/System32/config"))

    assert sent
    assert "路径不允许访问" in sent[0]
    assert not called


def test_normalize_compact_lark_event_restores_nested_shape(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        whisper_load_policy="lazy",
    ))

    event = bridge._normalize_event({
        "type": "im.message.receive_v1",
        "message_id": "om_1",
        "chat_id": "oc_1",
        "chat_type": "p2p",
        "message_type": "text",
        "content": "测试",
        "sender_id": "ou_1",
    })

    message = event["event"]["message"]
    sender = event["event"]["sender"]["sender_id"]
    assert message["message_id"] == "om_1"
    assert message["chat_id"] == "oc_1"
    assert message["chat_type"] == "p2p"
    assert json.loads(message["content"]) == {"text": "测试"}
    assert sender["user_id"] == "ou_1"


def test_normalize_raw_lark_event_preserves_audio_file_key(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        whisper_load_policy="lazy",
    ))

    raw = {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"user_id": "ou_1"}},
            "message": {
                "message_id": "om_audio",
                "chat_id": "oc_1",
                "chat_type": "p2p",
                "message_type": "audio",
                "content": json.dumps({"file_key": "file_v2_abc"}, ensure_ascii=False),
            },
        },
    }

    event = bridge._normalize_event(raw)

    message = event["event"]["message"]
    assert message["message_type"] == "audio"
    assert json.loads(message["content"])["file_key"] == "file_v2_abc"


def test_normalize_compact_file_event_parses_xml_file_metadata(tmp_path):
    bridge = Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
        whisper_load_policy="lazy",
    ))

    event = bridge._normalize_event({
        "type": "im.message.receive_v1",
        "message_id": "om_file",
        "chat_id": "oc_1",
        "chat_type": "p2p",
        "message_type": "file",
        "content": '<file key="file_v3_abc" name="guide.pdf"/>',
        "sender_id": "ou_1",
    })

    message = event["event"]["message"]
    assert message["message_type"] == "file"
    assert json.loads(message["content"]) == {
        "file_key": "file_v3_abc",
        "file_name": "guide.pdf",
    }
