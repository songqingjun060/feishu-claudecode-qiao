from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def test_initial_event_offset_starts_at_end_of_existing_file(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
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
        )
    )

    assert bridge._initial_event_offset() == 0


def test_bridge_event_dispatch_queues_without_processing_inline(tmp_path, monkeypatch):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
        )
    )
    queued = []

    monkeypatch.setattr(
        bridge,
        "_process_event",
        lambda event: (_ for _ in ()).throw(AssertionError("should not process inline")),
    )
    bridge.event_dispatcher.process = lambda event: queued.append(event)

    event = {
        "event": {
            "sender": {"sender_id": {"user_id": "ou_1"}},
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_1",
                "chat_type": "p2p",
                "message_type": "text",
                "content": "{\"text\":\"hi\"}",
            },
        }
    }

    bridge._dispatch_event(event)
    assert bridge.event_dispatcher.wait_idle(timeout=2)
    assert queued == [event]
    bridge.event_dispatcher.stop(timeout=2)
