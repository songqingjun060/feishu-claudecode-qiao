from pathlib import Path

import pytest

from feishu_claudecode_qiao.feishu_gateway import CurrentFeishuGateway, FeishuGateway


class RecordingBridge:
    def __init__(self):
        self.calls = []

    def _send_reply(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        reply_to_message_id: str = "",
    ) -> bool:
        self.calls.append(
            ("_send_reply", chat_id, content, msg_type, reply_to_message_id)
        )
        return True

    def _upload_file(self, path: str | Path) -> str:
        self.calls.append(("_upload_file", path))
        return "file_key_1"

    def _download_image(self, message_id: str, image_key: str) -> str:
        self.calls.append(("_download_image", message_id, image_key))
        return "image.png"

    def _add_message_reaction(self, message_id: str) -> str:
        self.calls.append(("_add_message_reaction", message_id))
        return "reaction_1"

    def _delete_message_reaction(self, message_id: str, reaction_id: str) -> bool:
        self.calls.append(("_delete_message_reaction", message_id, reaction_id))
        return True


def test_current_gateway_satisfies_gateway_protocol():
    assert isinstance(CurrentFeishuGateway(RecordingBridge()), FeishuGateway)


def test_send_message_delegates_to_bridge_send_reply_without_reply_target():
    bridge = RecordingBridge()
    gateway = CurrentFeishuGateway(bridge)

    assert gateway.send_message("oc_1", "hello", "text") is True

    assert bridge.calls == [("_send_reply", "oc_1", "hello", "text", "")]


def test_reply_message_delegates_to_bridge_reply_endpoint():
    bridge = RecordingBridge()
    gateway = CurrentFeishuGateway(bridge)

    assert gateway.reply_message("oc_1", "om_1", "hello", "text") is True

    assert bridge.calls == [("_send_reply", "oc_1", "hello", "text", "om_1")]


def test_file_and_reaction_methods_delegate_to_existing_bridge_methods(tmp_path):
    bridge = RecordingBridge()
    gateway = CurrentFeishuGateway(bridge)
    target = tmp_path / "report.txt"

    assert gateway.upload_file(target) == "file_key_1"
    assert gateway.download_file("om_1", "img_v3_1") == "image.png"
    assert gateway.add_reaction("om_1") == "reaction_1"
    assert gateway.delete_reaction("om_1", "reaction_1") is True

    assert bridge.calls == [
        ("_upload_file", target),
        ("_download_image", "om_1", "img_v3_1"),
        ("_add_message_reaction", "om_1"),
        ("_delete_message_reaction", "om_1", "reaction_1"),
    ]


def test_download_file_rejects_non_image_until_bridge_has_generic_download():
    gateway = CurrentFeishuGateway(RecordingBridge())

    with pytest.raises(NotImplementedError):
        gateway.download_file("om_1", "file_v1", resource_type="file")
