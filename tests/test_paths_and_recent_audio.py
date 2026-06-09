import json

from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config
from feishu_claudecode_qiao.commands import parse_command


def make_bridge(tmp_path):
    return Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path / "data"),
            claude_work_dir=str(tmp_path),
            security_allowed_paths=[str(tmp_path)],
        )
    )


def make_event(
    *,
    chat_id="oc_1",
    chat_type="group",
    sender="ou_1",
    msg_type="text",
    content_obj=None,
    mentions=None,
    message_id="om_1",
):
    return {
        "event": {
            "sender": {"sender_id": {"user_id": sender, "name": "tester"}},
            "message": {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "content": json.dumps(content_obj or {"text": ""}, ensure_ascii=False),
                "mentions": mentions or [],
                "message_id": message_id,
                "message_type": msg_type,
            },
        }
    }


def bot_mention():
    return [
        {
            "id": {"open_id": "cli_test", "union_id": "on_bot", "user_id": None},
            "key": "@_user_1",
            "mentioned_type": "bot",
            "name": "test-bot",
        }
    ]


def test_allowed_local_path_is_annotated_for_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path / "report.md"
    target.write_text("hello", encoding="utf-8")
    prompts = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event_body(
        make_event(
            chat_type="p2p",
            content_obj={"text": f"read this file {target}"},
        )
    )

    assert "<bridge_verified_paths>" in prompts[0]
    assert str(target.resolve()) in prompts[0]
    assert "type: file" in prompts[0]


def test_desktop_file_name_fragment_is_resolved_for_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    target = desktop / "feishu-claudecode-qiao-third-remediation-result.md"
    target.write_text("hello", encoding="utf-8")
    bridge._local_file_search_dirs = [desktop]
    prompts = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event_body(
        make_event(
            chat_type="p2p",
            content_obj={
                "text": (
                    "\u5206\u6790\u684c\u9762\u6587\u4ef6"
                    "feishu-claudecode-qiao-third-remediation-result"
                )
            },
        )
    )

    assert str(target.resolve()) in prompts[0]
    assert "type: file" in prompts[0]


def test_send_desktop_file_intent_uploads_without_calling_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    target = desktop / "feishu-claudecode-qiao-third-review-and-fix-plan.md"
    target.write_text("hello", encoding="utf-8")
    bridge._local_file_search_dirs = [desktop]
    sent = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Claude should not be called")
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={
                "text": (
                    "@_user_1 "
                    "\u53d1\u9001\u684c\u9762\u6587\u6863\u5230\u7fa4\u804a"
                    "feishu-claudecode-qiao-third-review-and-fix-plan"
                )
            },
            mentions=bot_mention(),
        )
    )

    assert sent == [("oc_1", str(target.resolve()), "om_1")]


def test_send_drive_file_intent_uploads_named_zip_without_calling_claude(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    drive_root = tmp_path / "D"
    drive_root.mkdir()
    target = drive_root / "feishu-claudecode-qiao-clean-package.zip"
    target.write_text("zip", encoding="utf-8")
    bridge._local_file_search_dirs = [drive_root]
    sent = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Claude should not be called")
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={
                "text": (
                    "@_user_1 上传D盘文件"
                    "feishu-claudecode-qiao-clean-package.ZIP到群内"
                )
            },
            mentions=bot_mention(),
        )
    )

    assert sent == [("oc_1", str(target.resolve()), "om_1")]


def test_at_mention_prefix_is_removed_before_command_parsing():
    cmd = parse_command("@_user_1 /workspace")

    assert cmd.is_command is True
    assert cmd.name == "workspace"


def test_generated_file_path_in_claude_reply_is_uploaded_when_user_asked(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path / "result.xlsx"
    target.write_text("xlsx", encoding="utf-8")
    sent_files = []
    replies = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (
            f"我无法上传。\nExcel 文件位置:\n```text\n{target}\n```",
            "sid_1",
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent_files.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )
    monkeypatch.setattr(
        bridge,
        "_send_event_reply",
        lambda chat_id, content, msg_type, chat_type, msg_id, sender, sender_name: replies.append(
            (content, msg_type)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={"text": "@_user_1 生成的文件直接上传到群里"},
            mentions=bot_mention(),
        )
    )

    assert sent_files == [("oc_1", str(target.resolve()), "om_1")]
    assert replies == [("已上传文件：result.xlsx", "text")]



def test_claude_reply_file_path_uploads_with_generic_group_upload_request(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path / "result.xlsx"
    target.write_text("xlsx", encoding="utf-8")
    sent_files = []
    replies = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (
            f"Cannot upload directly.\nExcel file location:\n```text\n{target}\n```",
            "sid_1",
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent_files.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )
    monkeypatch.setattr(
        bridge,
        "_send_event_reply",
        lambda chat_id, content, msg_type, chat_type, msg_id, sender, sender_name: replies.append(
            (content, msg_type)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={"text": "@_user_1 \u76f4\u63a5\u628a\u6587\u4ef6\u4e0a\u4f20\u5230\u7fa4\u5185"},
            mentions=bot_mention(),
        )
    )

    assert sent_files == [("oc_1", str(target.resolve()), "om_1")]
    assert replies == [("\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1aresult.xlsx", "text")]


def test_followup_uploads_recent_generated_excel_from_previous_reply(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path / "bi-result.xlsx"
    target.write_text("xlsx", encoding="utf-8")
    sent_files = []
    replies = []
    claude_calls = []

    def fake_call_claude(*args, **kwargs):
        claude_calls.append(args)
        return (
            f"查询完成。\n\nExcel: `{target}`",
            "sid_1",
        )

    monkeypatch.setattr(bridge, "_call_claude", fake_call_claude)
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent_files.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )
    monkeypatch.setattr(
        bridge,
        "_send_event_reply",
        lambda chat_id, content, msg_type, chat_type, msg_id, sender, sender_name: replies.append(
            (content, msg_type)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={
                "text": "@_user_1 Q202605270017-5/7 \u67e5\u8be2BI\u7269\u6d41\u7801"
            },
            mentions=bot_mention(),
            message_id="om_query",
        )
    )
    bridge._process_event_body(
        make_event(
            content_obj={"text": "@_user_1 \u751f\u6210\u7684\u8868\u683c\u53d1\u4e0a\u6765"},
            mentions=bot_mention(),
            message_id="om_upload",
        )
    )

    assert len(claude_calls) == 1
    assert sent_files == [("oc_1", str(target.resolve()), "om_query")]
    assert replies[0] == ("\u67e5\u8be2\u5b8c\u6210\uff0c\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1abi-result.xlsx", "text")
    assert replies[-1] == ("\u521a\u624d\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1abi-result.xlsx", "text")


def test_followup_summary_table_request_calls_claude_instead_of_reuploading(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    old_file = tmp_path / "bi-result-old.xlsx"
    old_file.write_text("old", encoding="utf-8")
    new_file = tmp_path / "bi-result-summary.xlsx"
    new_file.write_text("new", encoding="utf-8")
    sent_files = []
    replies = []
    prompts = []

    bridge._cache_recent_file_path("oc_1", str(old_file), uploaded=True)

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt)
        or (f"已汇总为最新表格: `{new_file}`", "sid_1"),
    )
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent_files.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )
    monkeypatch.setattr(
        bridge,
        "_send_event_reply",
        lambda chat_id, content, msg_type, chat_type, msg_id, sender, sender_name: replies.append(
            (content, msg_type)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={"text": "@_user_1 汇总为最新表格发出来"},
            mentions=bot_mention(),
            message_id="om_summary",
        )
    )

    assert len(prompts) == 1
    assert sent_files == [("oc_1", str(new_file.resolve()), "om_summary")]
    assert "刚才已上传文件" not in "".join(content for content, _ in replies)


def test_bi_query_generated_excel_is_uploaded_immediately(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    target = tmp_path / "bi-result.xlsx"
    target.write_text("xlsx", encoding="utf-8")
    sent_files = []
    replies = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (
            f"查询完成。\n\nQ202605270017-5/7 一共 170 个物流码。\n\nExcel: `{target}`",
            "sid_1",
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_local_file",
        lambda chat_id, path, reply_to_message_id="": sent_files.append(
            (chat_id, path, reply_to_message_id)
        )
        or True,
    )
    monkeypatch.setattr(
        bridge,
        "_send_event_reply",
        lambda chat_id, content, msg_type, chat_type, msg_id, sender, sender_name: replies.append(
            (content, msg_type)
        )
        or True,
    )

    bridge._process_event_body(
        make_event(
            content_obj={
                "text": "@_user_1 Q202605270017-5/7 \u67e5\u8be2BI\u7269\u6d41\u7801"
            },
            mentions=bot_mention(),
        )
    )

    assert sent_files == [("oc_1", str(target.resolve()), "om_1")]
    assert replies == [("\u67e5\u8be2\u5b8c\u6210\uff0c\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1abi-result.xlsx", "text")]


def test_unmentioned_group_audio_is_cached_when_event_arrives(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)

    monkeypatch.setattr(bridge, "_call_claude", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Claude should not be called")))
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reply should not be sent")))

    bridge._process_event(
        make_event(
            msg_type="audio",
            content_obj={"file_key": "audio_key_1"},
            mentions=[],
            message_id="om_audio_1",
        )
    )

    cached = bridge._recent_audio_by_chat["oc_1"]
    assert cached["message_id"] == "om_audio_1"
    assert cached["content_obj"]["file_key"] == "audio_key_1"


def test_followup_analysis_uses_recent_uploaded_file_context(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    saved = tmp_path / "uploaded.pdf"
    saved.write_text("pdf", encoding="utf-8")
    prompts = []

    monkeypatch.setattr(bridge, "_process_file", lambda msg_id, content_obj: str(saved))
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_event_reply", lambda *args, **kwargs: True)

    bridge._process_event_body(
        make_event(
            chat_type="p2p",
            msg_type="file",
            content_obj={"file_key": "file_v3_abc", "file_name": "guide.pdf"},
            message_id="om_file",
        )
    )
    bridge._process_event_body(
        make_event(
            chat_type="p2p",
            content_obj={"text": "\u5206\u6790\u4e00\u4e0b\u8fd9\u4e2a\u6587\u4ef6"},
            message_id="om_followup",
        )
    )

    assert len(prompts) == 2
    assert str(saved.resolve()) in prompts[-1]
    assert "bridge_recent_file" in prompts[-1]
    assert "pypdf or pdfplumber" in prompts[-1]
    assert "Do not rely on pdftoppm as the first option" in prompts[-1]


def test_unmentioned_group_file_is_cached_when_event_arrives(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    saved = tmp_path / "codes.xlsx"
    saved.write_text("xlsx", encoding="utf-8")

    monkeypatch.setattr(bridge, "_process_file", lambda msg_id, content_obj: str(saved))
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Claude should not be called")
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_send_reply",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reply should not be sent")
        ),
    )

    bridge._process_event(
        make_event(
            msg_type="file",
            content_obj={"file_key": "file_v3_abc", "file_name": "codes.xlsx"},
            mentions=[],
            message_id="om_file_1",
        )
    )

    cached = bridge._recent_files_by_chat["oc_1"]
    assert cached["files"] == [str(saved.resolve())]


def test_bare_mention_after_group_file_uses_cached_file_context(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    saved = tmp_path / "codes.xlsx"
    saved.write_text("xlsx", encoding="utf-8")
    prompts = []

    monkeypatch.setattr(bridge, "_process_file", lambda msg_id, content_obj: str(saved))
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="file",
            content_obj={"file_key": "file_v3_abc", "file_name": "codes.xlsx"},
            mentions=[],
            message_id="om_file_1",
        )
    )
    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1"},
            mentions=bot_mention(),
            message_id="om_text_1",
        )
    )

    assert str(saved.resolve()) in prompts[-1]
    assert "bridge_recent_file" in prompts[-1]
    assert "openpyxl or pandas" in prompts[-1]


def test_followup_bi_query_after_group_file_uses_cached_file_context(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    saved = tmp_path / "codes.xlsx"
    saved.write_text("xlsx", encoding="utf-8")
    prompts = []

    monkeypatch.setattr(bridge, "_process_file", lambda msg_id, content_obj: str(saved))
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="file",
            content_obj={"file_key": "file_v3_abc", "file_name": "codes.xlsx"},
            mentions=[],
            message_id="om_file_1",
        )
    )
    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1 BI物流码查询"},
            mentions=bot_mention(),
            message_id="om_text_1",
        )
    )

    assert str(saved.resolve()) in prompts[-1]
    assert "bridge_recent_file" in prompts[-1]


def test_p2p_uses_admin_permission_profile_by_default(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    permission_modes = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda *args, **kwargs: permission_modes.append(kwargs.get("permission_mode"))
        or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_event_reply", lambda *args, **kwargs: True)

    bridge._process_event_body(
        make_event(
            chat_type="p2p",
            content_obj={"text": "\u5206\u6790\u4e00\u4e0b"},
            message_id="om_p2p",
        )
    )

    assert permission_modes == ["bypassPermissions"]


def test_video_file_hint_tells_claude_to_use_ffmpeg(tmp_path):
    bridge = make_bridge(tmp_path)
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake video")

    content = bridge._append_file_tool_hints(f"[文件] {video}")

    assert "ffprobe/ffmpeg" in content
    assert "extract a few representative frames" in content
    assert str(video.resolve()) in content


def test_mentioned_recent_audio_request_uses_cached_audio(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    prompts = []
    transcribed = "\u8fd9\u662f\u8bed\u97f3\u8f6c\u5199"

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda *args, **kwargs: "reaction_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(bridge, "_process_audio", lambda *args, **kwargs: transcribed)
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="audio",
            content_obj={"file_key": "audio_key_1"},
            mentions=[],
            message_id="om_audio_1",
        )
    )
    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1 \u8bfb\u521a\u624d\u7684\u8bed\u97f3\u6d88\u606f"},
            mentions=bot_mention(),
            message_id="om_text_1",
        )
    )

    assert transcribed in prompts[-1]
    assert "bridge_recent_audio_transcript" in prompts[-1]


def test_generic_previous_message_after_own_group_audio_uses_cached_audio(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    prompts = []
    transcribed = "\u8fd9\u662f\u4e0a\u4e00\u6761\u8bed\u97f3\u8f6c\u5199"

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda *args, **kwargs: "reaction_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(bridge, "_process_audio", lambda *args, **kwargs: transcribed)
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="audio",
            content_obj={"file_key": "audio_key_1"},
            mentions=[],
            sender="ou_1",
            message_id="om_audio_1",
        )
    )
    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1 \u8bfb\u4e0a\u4e00\u6761\u6d88\u606f"},
            mentions=bot_mention(),
            sender="ou_1",
            message_id="om_text_1",
        )
    )

    assert transcribed in prompts[-1]
    assert "bridge_recent_audio_transcript" in prompts[-1]


def test_bare_mention_after_own_group_audio_uses_cached_audio(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    prompts = []
    transcribed = "\u53ea\u0040\u4e5f\u80fd\u8bfb\u8bed\u97f3"

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda *args, **kwargs: "reaction_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(bridge, "_process_audio", lambda *args, **kwargs: transcribed)
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="audio",
            content_obj={"file_key": "audio_key_1"},
            mentions=[],
            sender="ou_1",
            message_id="om_audio_1",
        )
    )
    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1 "},
            mentions=bot_mention(),
            sender="ou_1",
            message_id="om_text_1",
        )
    )

    assert transcribed in prompts[-1]
    assert "bridge_recent_audio_transcript" in prompts[-1]


def test_bare_mention_does_not_use_another_sender_cached_audio(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    prompts = []

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda *args, **kwargs: "reaction_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        bridge,
        "_process_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("other sender audio should not be transcribed")
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="audio",
            content_obj={"file_key": "audio_key_1"},
            mentions=[],
            sender="ou_other",
            message_id="om_audio_1",
        )
    )
    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1 "},
            mentions=bot_mention(),
            sender="ou_1",
            message_id="om_text_1",
        )
    )

    assert prompts
    assert "bridge_recent_audio_transcript" not in prompts[-1]


def test_mentioned_recent_audio_request_fetches_group_history_when_cache_misses(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    prompts = []
    transcribed = "\u7fa4\u5386\u53f2\u8bed\u97f3\u8f6c\u5199"

    monkeypatch.setattr(bridge, "_add_message_reaction", lambda *args, **kwargs: "reaction_1")
    monkeypatch.setattr(bridge, "_delete_message_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        bridge,
        "_fetch_recent_group_media",
        lambda chat_id, media_type="audio": {
            "message_id": "om_audio_history",
            "content_obj": {"file_key": "audio_key_history"},
        },
    )
    monkeypatch.setattr(bridge, "_process_audio", lambda *args, **kwargs: transcribed)
    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, *args, **kwargs: prompts.append(prompt) or ("ok", "sid_1"),
    )
    monkeypatch.setattr(bridge, "_send_reply", lambda *args, **kwargs: True)

    bridge._process_event(
        make_event(
            msg_type="text",
            content_obj={"text": "@_user_1 \u8bfb\u521a\u624d\u7684\u8bed\u97f3\u6d88\u606f"},
            mentions=bot_mention(),
            message_id="om_text_1",
        )
    )

    assert transcribed in prompts[-1]
    assert "bridge_recent_audio_transcript" in prompts[-1]
