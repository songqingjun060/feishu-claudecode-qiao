from feishu_claudecode_qiao.media_pipeline import MediaBatcher, MediaItem, RecentContext


def test_p2p_media_messages_from_same_chat_merge_with_followup_text():
    batcher = MediaBatcher(window_seconds=10)

    first = batcher.add_media(
        chat_id="oc_1",
        chat_type="p2p",
        sender_id="ou_1",
        item=MediaItem(kind="image", message_id="om_img_1", path="D:/a.png"),
        now=100.0,
    )
    second = batcher.add_text(
        chat_id="oc_1",
        chat_type="p2p",
        sender_id="ou_1",
        message_id="om_text_1",
        text="识别这个箱唛",
        mentioned=True,
        reply_to_bot=False,
        now=105.0,
    )

    assert first.batch_id == second.batch_id
    assert second.items[0].path == "D:/a.png"
    assert second.texts == ["识别这个箱唛"]


def test_group_media_does_not_merge_across_senders():
    batcher = MediaBatcher(window_seconds=10)

    first = batcher.add_media(
        chat_id="oc_1",
        chat_type="group",
        sender_id="ou_a",
        item=MediaItem(kind="image", message_id="om_img_1", path="D:/a.png"),
        now=100.0,
    )
    second = batcher.add_text(
        chat_id="oc_1",
        chat_type="group",
        sender_id="ou_b",
        message_id="om_text_1",
        text="分析一下",
        mentioned=True,
        reply_to_bot=False,
        now=105.0,
    )

    assert first.batch_id != second.batch_id
    assert second.items == []


def test_group_text_must_mention_or_reply_to_merge_media():
    batcher = MediaBatcher(window_seconds=10)
    media = batcher.add_media(
        chat_id="oc_1",
        chat_type="group",
        sender_id="ou_1",
        item=MediaItem(kind="image", message_id="om_img_1", path="D:/a.png"),
        now=100.0,
    )

    unrelated = batcher.add_text(
        chat_id="oc_1",
        chat_type="group",
        sender_id="ou_1",
        message_id="om_text_1",
        text="普通聊天",
        mentioned=False,
        reply_to_bot=False,
        now=102.0,
    )
    mentioned = batcher.add_text(
        chat_id="oc_1",
        chat_type="group",
        sender_id="ou_1",
        message_id="om_text_2",
        text="识别这个",
        mentioned=True,
        reply_to_bot=False,
        now=103.0,
    )

    assert unrelated.batch_id != media.batch_id
    assert mentioned.batch_id == media.batch_id


def test_media_batch_renders_file_context():
    batcher = MediaBatcher(window_seconds=10)
    batcher.add_media(
        chat_id="oc_1",
        chat_type="p2p",
        sender_id="ou_1",
        item=MediaItem(kind="image", message_id="om_img_1", path="D:/a.png"),
        now=100.0,
    )
    batch = batcher.add_text(
        chat_id="oc_1",
        chat_type="p2p",
        sender_id="ou_1",
        message_id="om_text_1",
        text="识别图片里的物流码",
        mentioned=False,
        reply_to_bot=False,
        now=105.0,
    )

    rendered = batcher.render_context(batch)

    assert "<bridge_media_batch>" in rendered
    assert "kind: image" in rendered
    assert "D:/a.png" in rendered
    assert "识别图片里的物流码" in rendered


def test_recent_context_tracks_generated_files_and_upload_state():
    context = RecentContext()

    context.remember_generated_file("oc_1", "D:/result.xlsx", source_message_id="om_1", uploaded=False)
    latest = context.latest_generated_file("oc_1")
    context.mark_uploaded("oc_1", "D:/result.xlsx")

    assert latest is not None
    assert latest.path == "D:/result.xlsx"
    assert latest.source_message_id == "om_1"
    assert context.latest_generated_file("oc_1").uploaded is True
