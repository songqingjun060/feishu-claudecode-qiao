import json

from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def make_text_event(
    chat_id: str,
    message_id: str,
    text: str,
    sender: str = "ou_1",
) -> dict:
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender}},
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        }
    }


def make_file_event(
    chat_id: str,
    message_id: str,
    sender: str = "ou_1",
) -> dict:
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender}},
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": "p2p",
                "message_type": "file",
                "content": json.dumps(
                    {"file_key": "file_v3_abc", "file_name": "codes.xlsx"},
                    ensure_ascii=False,
                ),
            },
        }
    }


def test_initial_event_offset_starts_at_end_of_existing_file(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_message_coalesce_window_seconds=0,
            bridge_text_coalesce_window_seconds=0,
        )
    )
    bridge.ws_events_file.parent.mkdir(parents=True, exist_ok=True)
    bridge.ws_events_file.write_text("old event\n", encoding="utf-8")

    assert bridge._initial_event_offset() == bridge.ws_events_file.stat().st_size


def test_initial_event_offset_is_zero_when_file_missing(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_message_coalesce_window_seconds=0,
            bridge_text_coalesce_window_seconds=0,
        )
    )

    assert bridge._initial_event_offset() == 0


def test_bridge_event_dispatch_queues_without_processing_inline(tmp_path, monkeypatch):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
            bridge_message_coalesce_window_seconds=0,
            bridge_text_coalesce_window_seconds=0,
        )
    )
    queued = []

    monkeypatch.setattr(
        bridge,
        "_process_event",
        lambda event: (_ for _ in ()).throw(AssertionError("should not process inline")),
    )
    bridge.event_dispatcher.process = lambda event: queued.append(event)

    event = make_text_event("oc_1", "om_1", "hi")

    bridge._dispatch_event(event)
    assert bridge.event_dispatcher.wait_idle(timeout=2)
    assert queued == [event]
    bridge.event_dispatcher.stop(timeout=2)


def test_bridge_coalesces_same_sender_text_events(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
        )
    )

    merged = bridge._coalesce_chat_events(
        [
            make_text_event("oc_1", "om_1", "first"),
            make_text_event("oc_1", "om_2", "second"),
        ]
    )

    assert isinstance(merged, dict)
    message = merged["event"]["message"]
    assert message["message_id"] == "om_2"
    assert "first" in message["content"]
    assert "second" in message["content"]


def test_bridge_coalesces_mixed_media_into_last_text_with_context(tmp_path, monkeypatch):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
        )
    )
    cached = tmp_path / "codes.xlsx"
    cached.write_text("codes", encoding="utf-8")
    monkeypatch.setattr(bridge, "_process_file", lambda msg_id, content_obj: str(cached))
    events = [
        make_file_event("oc_1", "om_file"),
        make_text_event("oc_1", "om_text", "process the table"),
    ]

    merged = bridge._coalesce_chat_events(events)

    assert isinstance(merged, dict)
    assert merged["event"]["message"]["message_id"] == "om_text"
    bridge._preprocess_coalesced_event(merged)
    assert bridge._recent_files_by_chat["oc_1"]["files"] == [str(cached.resolve())]
