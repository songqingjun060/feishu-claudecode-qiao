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
