import json

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


def test_prepare_text_content_wraps_plain_text(tmp_path):
    bridge = make_bridge(tmp_path)
    content = bridge._prepare_message_content("hello", "text")
    assert json.loads(content) == {"text": "hello"}


def test_prepare_text_content_keeps_existing_text_json(tmp_path):
    bridge = make_bridge(tmp_path)
    original = '{"text":"hello"}'
    assert bridge._prepare_message_content(original, "text") == original


def test_prepare_interactive_content_is_not_wrapped(tmp_path):
    bridge = make_bridge(tmp_path)
    card = '{"config":{"wide_screen_mode":true},"elements":[]}'
    assert bridge._prepare_message_content(card, "interactive") == card


def test_send_reply_does_not_prefix_status_emoji(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    sent = []

    class FakeResponse:
        def json(self):
            return {"code": 0, "msg": "success"}

    def fake_post(url, **kwargs):
        sent.append(kwargs["json"])
        return FakeResponse()

    monkeypatch.setattr(bridge, "_get_token", lambda: "tenant-token")
    monkeypatch.setattr("feishu_claudecode_qiao.bridge.requests.post", fake_post)

    assert bridge._send_reply("oc_1", "hello") is True
    assert json.loads(sent[0]["content"]) == {"text": "hello"}


def test_send_reply_to_message_uses_feishu_reply_endpoint(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    sent = []

    class FakeResponse:
        def json(self):
            return {"code": 0, "msg": "success"}

    def fake_post(url, **kwargs):
        sent.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(bridge, "_get_token", lambda: "tenant-token")
    monkeypatch.setattr("feishu_claudecode_qiao.bridge.requests.post", fake_post)

    assert bridge._send_reply("oc_1", "hello", "text", reply_to_message_id="om_1") is True

    url, kwargs = sent[0]
    assert url.endswith("/open-apis/im/v1/messages/om_1/reply")
    assert "params" not in kwargs
    assert kwargs["json"]["msg_type"] == "text"
    assert kwargs["json"]["reply_in_thread"] is False
    assert json.loads(kwargs["json"]["content"]) == {"text": "hello"}


def test_group_text_reply_mentions_sender(tmp_path):
    bridge = make_bridge(tmp_path)
    content = bridge._with_group_mention(
        '{"text":"hello"}',
        "text",
        "ou_sender",
        "Sender",
    )

    assert json.loads(content) == {
        "text": '<at user_id="ou_sender">Sender</at> hello'
    }


def test_group_interactive_reply_mentions_sender(tmp_path):
    bridge = make_bridge(tmp_path)
    card = '{"config":{"wide_screen_mode":true},"elements":[]}'

    content = bridge._with_group_mention(card, "interactive", "ou_sender", "Sender")
    data = json.loads(content)

    assert data["elements"][0]["text"]["content"] == "<at id=ou_sender></at>"


def test_send_local_file_uploads_and_sends_file_message(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path / "report.md"
    target.write_text("hello", encoding="utf-8")
    sent = []

    monkeypatch.setattr(bridge, "_upload_file", lambda path: "file_key_1")
    monkeypatch.setattr(
        bridge,
        "_send_reply",
        lambda chat_id, content, msg_type="text", reply_to_message_id="": sent.append(
            (chat_id, content, msg_type, reply_to_message_id)
        )
        or True,
    )

    assert bridge._send_local_file("oc_1", str(target)) is True

    assert sent == [
        (
            "oc_1",
            json.dumps({"file_key": "file_key_1"}, ensure_ascii=False),
            "file",
            "",
        )
    ]
