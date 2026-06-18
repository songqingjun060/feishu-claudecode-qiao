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


def make_text_event(chat_id="oc_1", sender="ou_1", text="hello"):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "om_1",
                "chat_type": "p2p",
                "chat_id": chat_id,
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        }
    }


def make_post_event(chat_id="oc_1", sender="ou_1"):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "om_post",
                "chat_type": "p2p",
                "chat_id": chat_id,
                "message_type": "post",
                "content": json.dumps(
                    {
                        "title": "",
                        "content": [
                            [{"tag": "img", "image_key": "img_v3_abc"}],
                            [{"tag": "text", "text": "识别图片内容", "style": []}],
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        }
    }


def make_image_marker_event(chat_id="oc_1", sender="ou_1"):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "om_image",
                "chat_type": "p2p",
                "chat_id": chat_id,
                "message_type": "image",
                "content": "[Image: img_v3_marker]",
            },
        }
    }


def make_post_image_marker_event(chat_id="oc_1", sender="ou_1"):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "om_post_marker",
                "chat_type": "p2p",
                "chat_id": chat_id,
                "message_type": "post",
                "content": "[Image: img_v3_post_marker]\nBI物流码查询",
            },
        }
    }


def make_multi_post_image_marker_event(chat_id="oc_1", sender="ou_1"):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "om_post_multi",
                "chat_type": "p2p",
                "chat_id": chat_id,
                "message_type": "post",
                "content": (
                    "[Image: img_v3_multi_1]\n"
                    "[Image: img_v3_multi_2]\n"
                    "\u8bfb\u53d6\u56fe\u7247\u5185\u7269\u6d41\u7801"
                ),
            },
        }
    }


def make_group_image_marker_event(chat_id="oc_group", sender="ou_1"):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "message_id": "om_group_image",
                "chat_type": "group",
                "chat_id": chat_id,
                "message_type": "image",
                "content": "[Image: img_v3_group_marker]",
                "mentions": [],
            },
        }
    }


def test_process_post_event_downloads_embedded_image_and_passes_path_to_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: True)
    monkeypatch.setattr(bridge, "_download_image", lambda message_id, image_key: calls.append(("download", message_id, image_key)) or str(image_path))
    monkeypatch.setattr(bridge, "_call_claude", lambda prompt, *args, **kwargs: calls.append(("claude", prompt)) or ("reply", "sid_1"))
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(make_post_event())

    assert ("download", "om_post", "img_v3_abc") in calls
    assert any(call[0] == "claude" and str(image_path) in call[1] for call in calls)
    assert any(call[0] == "claude" and "For images, inspect the local image directly" in call[1] for call in calls)


def test_process_image_marker_event_caches_image_without_calling_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: True)
    monkeypatch.setattr(bridge, "_download_image", lambda message_id, image_key: calls.append(("download", message_id, image_key)) or str(image_path))
    monkeypatch.setattr(bridge, "_call_claude", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Claude should not be called for a bare image")))
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("bare image should not send a reply")))

    bridge._process_event(make_image_marker_event())

    assert ("download", "om_image", "img_v3_marker") in calls
    assert bridge._recent_files_by_chat["oc_1"]["files"] == [str(image_path.resolve())]


def test_followup_after_bare_images_uses_all_cached_image_paths_once(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    image_1 = tmp_path / "image-1.png"
    image_2 = tmp_path / "image-2.png"
    image_1.write_bytes(b"fake image 1")
    image_2.write_bytes(b"fake image 2")
    prompts = []

    def fake_download(message_id, image_key):
        return str(image_1 if image_key.endswith("_1") else image_2)

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: True)
    monkeypatch.setattr(bridge, "_download_image", fake_download)
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("reply", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_image_marker_event()
        | {
            "event": {
                "sender": {"sender_id": {"user_id": "ou_1", "name": "tester"}},
                "message": {
                    "message_id": "om_image_1",
                    "chat_type": "p2p",
                    "chat_id": "oc_1",
                    "message_type": "image",
                    "content": "[Image: img_v3_marker_1]",
                },
            }
        }
    )
    bridge._process_event(
        make_image_marker_event()
        | {
            "event": {
                "sender": {"sender_id": {"user_id": "ou_1", "name": "tester"}},
                "message": {
                    "message_id": "om_image_2",
                    "chat_type": "p2p",
                    "chat_id": "oc_1",
                    "message_type": "image",
                    "content": "[Image: img_v3_marker_2]",
                },
            }
        }
    )

    assert prompts == []

    bridge._process_event(
        make_text_event(text="\u8bfb\u53d6\u521a\u624d\u56fe\u7247\u8fdb\u884c\u7269\u6d41\u7801\u67e5\u8be2")
    )

    assert len(prompts) == 1
    assert "bridge_media_batch" in prompts[0]
    assert "bridge_recent_file" in prompts[0]
    assert str(image_1.resolve()) in prompts[0]
    assert str(image_2.resolve()) in prompts[0]


def test_group_unmentioned_image_is_cached_without_reply(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    image_path = tmp_path / "group-image.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(bridge, "_download_image", lambda message_id, image_key: str(image_path))
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Claude should not be called for an unmentioned group image")
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_reply",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unmentioned group image should not send a reply")
        ),
    )

    bridge._process_event(make_group_image_marker_event())

    assert bridge._recent_files_by_chat["oc_group"]["files"] == [str(image_path.resolve())]


def test_multi_image_post_passes_every_image_path_to_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    image_1 = tmp_path / "multi-1.png"
    image_2 = tmp_path / "multi-2.png"
    image_1.write_bytes(b"fake image 1")
    image_2.write_bytes(b"fake image 2")
    prompts = []

    def fake_download(message_id, image_key):
        return str(image_1 if image_key.endswith("_1") else image_2)

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: True)
    monkeypatch.setattr(bridge, "_download_image", fake_download)
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("reply", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(make_multi_post_image_marker_event())

    assert len(prompts) == 1
    assert str(image_1.resolve()) in prompts[0]
    assert str(image_2.resolve()) in prompts[0]


def test_process_post_image_marker_event_downloads_image_key_from_lark_cli(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: True)
    monkeypatch.setattr(bridge, "_download_image", lambda message_id, image_key: calls.append(("download", message_id, image_key)) or str(image_path))
    monkeypatch.setattr(bridge, "_call_claude", lambda prompt, *args, **kwargs: calls.append(("claude", prompt)) or ("reply", "sid_1"))
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(make_post_image_marker_event())

    assert ("download", "om_post_marker", "img_v3_post_marker") in calls
    assert any(call[0] == "claude" and str(image_path) in call[1] for call in calls)
    assert any(call[0] == "claude" and "BI物流码查询" in call[1] for call in calls)


def test_process_event_accepts_raw_sender_without_user_id(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    sent = []

    event = make_text_event(sender=None)
    sender_id = event["event"]["sender"]["sender_id"]
    sender_id["open_id"] = "ou_open"
    sender_id["union_id"] = "on_union"
    sender_id.pop("name", None)

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: True)
    monkeypatch.setattr(bridge, "_call_claude", lambda *args, **kwargs: ("reply", "sid_1"))
    monkeypatch.setattr(bridge, "_send_reply", lambda chat_id, content, msg_type="text": sent.append(content) or True)

    bridge._process_event(event)

    assert sent
    assert bridge.session_store.get("chat:oc_1").session_id == "sid_1"


def test_add_message_reaction_posts_receive_emoji(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []

    class FakeResponse:
        def json(self):
            return {"code": 0, "data": {"reaction_id": "r_1"}}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(bridge, "_get_token", lambda: "tenant-token")
    monkeypatch.setattr("feishu_claudecode_qiao.bridge.requests.post", fake_post)

    reaction_id = bridge._add_message_reaction("om_1")

    assert reaction_id == "r_1"
    assert calls[0][0].endswith("/open-apis/im/v1/messages/om_1/reactions")
    assert calls[0][1]["json"] == {"reaction_type": {"emoji_type": "OK"}}


def test_add_message_reaction_failure_does_not_raise(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    monkeypatch.setattr(bridge, "_get_token", lambda: (_ for _ in ()).throw(RuntimeError("token failed")))

    assert bridge._add_message_reaction("om_1") is None


def test_delete_message_reaction_deletes_returned_reaction_id(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []

    class FakeResponse:
        def json(self):
            return {"code": 0, "msg": "success"}

    def fake_delete(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(bridge, "_get_token", lambda: "tenant-token")
    monkeypatch.setattr("feishu_claudecode_qiao.bridge.requests.delete", fake_delete)

    assert bridge._delete_message_reaction("om_1", "r_1") is True
    assert calls[0][0].endswith("/open-apis/im/v1/messages/om_1/reactions/r_1")


def test_delete_message_reaction_failure_does_not_raise(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    monkeypatch.setattr(bridge, "_get_token", lambda: (_ for _ in ()).throw(RuntimeError("token failed")))

    assert bridge._delete_message_reaction("om_1", "r_1") is False


def test_process_event_adds_and_removes_message_reaction(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = []

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda message_id: calls.append(("add", message_id)) or "r_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda message_id, reaction_id: calls.append(("delete", message_id, reaction_id)) or True)
    monkeypatch.setattr(bridge, "_call_claude", lambda *args, **kwargs: ("reply", "sid_1"))
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: calls.append(("reply", args[0], args[1])) or True)

    bridge._process_event(make_text_event())

    assert calls[0] == ("add", "om_1")
    assert calls[1][0] == "reply"
    assert calls[1][1] == "oc_1"
    assert json.loads(calls[1][2]) == {"text": "reply"}
    assert calls[-1] == ("delete", "om_1", "r_1")
