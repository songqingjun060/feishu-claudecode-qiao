from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def make_bridge(tmp_path):
    return Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            whisper_load_policy="lazy",
        )
    )


def test_group_bot_mention_accepts_current_bot_open_id(tmp_path):
    bridge = make_bridge(tmp_path)
    mentions = [
        {
            "id": {"open_id": "cli_test", "union_id": "on_bot", "user_id": None},
            "key": "@_user_1",
            "mentioned_type": "bot",
            "name": "test-bot",
        }
    ]

    assert bridge._is_mentioned("@_user_1 ping", "bot", mentions) is True


def test_group_bot_mention_rejects_other_bot(tmp_path):
    bridge = make_bridge(tmp_path)
    mentions = [
        {
            "id": {"open_id": "ou_other_bot", "union_id": "on_other", "user_id": None},
            "key": "@_user_1",
            "mentioned_type": "bot",
            "name": "other-bot",
        }
    ]

    assert bridge._is_mentioned("@_user_1 ping", "test-bot", mentions) is False
