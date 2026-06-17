from pathlib import Path

import pytest

from feishu_claudecode_qiao.feishu_gateway import (
    CurrentFeishuGateway,
    FeishuEventSubscriber,
    FeishuGateway,
    LarkOapiFeishuGateway,
    LarkOapiWebSocketSubscriber,
    StartWsEventSubscriber,
    create_event_subscriber,
    create_feishu_gateway,
)
from feishu_claudecode_qiao.config import Config


class RecordingBridge:
    def __init__(self):
        self.calls = []
        self.bridge_logger = type(
            "Logger",
            (),
            {"warning": lambda _self, message: self.calls.append(("warning", message))},
        )()

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


def test_start_ws_event_subscriber_satisfies_subscriber_protocol(tmp_path):
    subscriber = StartWsEventSubscriber(tmp_path / "config.toml", "qiao-test")

    assert isinstance(subscriber, FeishuEventSubscriber)


def test_start_ws_event_subscriber_delegates_lifecycle_to_start_ws(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("feishu_claudecode_qiao.feishu_gateway.subprocess.run", fake_run)

    subscriber = StartWsEventSubscriber(tmp_path / "config.toml", "qiao-test")

    assert subscriber.start(force=True) is True
    assert subscriber.stop() is True
    assert subscriber.restart(force=True) is True
    assert subscriber.status() is True

    actions = [call[0][2] for call in calls]
    assert actions == ["start", "stop", "restart", "status"]
    for args, _ in calls:
        assert "--config" in args
        assert str((tmp_path / "config.toml").resolve()) in args
        assert "--profile" in args
        assert "qiao-test" in args


def test_gateway_factory_keeps_current_backend_by_default(tmp_path):
    bridge = RecordingBridge()
    config = Config()

    gateway = create_feishu_gateway(config, bridge)
    subscriber = create_event_subscriber(config, tmp_path / "config.toml")

    assert isinstance(gateway, CurrentFeishuGateway)
    assert isinstance(subscriber, StartWsEventSubscriber)


def test_gateway_factory_rejects_unimplemented_lark_oapi_backend(tmp_path):
    bridge = RecordingBridge()
    config = Config(
        feishu_gateway_backend="lark_oapi",
        feishu_event_backend="lark_oapi_ws",
    )

    with pytest.raises(NotImplementedError):
        create_feishu_gateway(config, bridge)
    with pytest.raises(NotImplementedError):
        create_event_subscriber(config, tmp_path / "config.toml")

    assert issubclass(LarkOapiFeishuGateway, CurrentFeishuGateway) is False
    assert issubclass(LarkOapiWebSocketSubscriber, StartWsEventSubscriber) is False


def test_lark_oapi_placeholder_warns_before_raising():
    calls = []
    logger = type("Logger", (), {"warning": lambda _self, message: calls.append(message)})()

    with pytest.raises(NotImplementedError):
        LarkOapiFeishuGateway(Config(), logger=logger)

    assert calls
    assert "尚未实现" in calls[0]
