"""飞书 API 边界接口。

本模块先定义一层很窄的飞书操作网关，暂不切换生产桥的调用链路。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class FeishuGateway(Protocol):
    """飞书消息、文件和表情反应操作边界。"""

    def send_message(
        self, chat_id: str, content: str, msg_type: str = "text"
    ) -> bool:
        """向会话发送消息。"""

    def reply_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        msg_type: str = "text",
    ) -> bool:
        """回复一条已有消息。"""

    def upload_file(self, path: str | Path) -> str | None:
        """上传本地文件并返回飞书文件 key。"""

    def download_file(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "image",
    ) -> str | None:
        """下载飞书资源并返回本地路径。"""

    def add_reaction(self, message_id: str) -> str | None:
        """给消息添加表情反应并返回 reaction id。"""

    def delete_reaction(self, message_id: str, reaction_id: str) -> bool:
        """删除消息上的表情反应。"""


class CurrentFeishuGateway:
    """当前 Bridge 飞书方法的薄适配器。"""

    def __init__(self, bridge: object):
        self._bridge = bridge

    def send_message(
        self, chat_id: str, content: str, msg_type: str = "text"
    ) -> bool:
        return self._bridge._send_reply(chat_id, content, msg_type)

    def reply_message(
        self,
        chat_id: str,
        message_id: str,
        content: str,
        msg_type: str = "text",
    ) -> bool:
        return self._bridge._send_reply(
            chat_id,
            content,
            msg_type,
            reply_to_message_id=message_id,
        )

    def upload_file(self, path: str | Path) -> str | None:
        return self._bridge._upload_file(path)

    def download_file(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "image",
    ) -> str | None:
        if resource_type != "image":
            raise NotImplementedError(
                "当前 Bridge 只通过 _download_image 暴露图片下载能力"
            )
        return self._bridge._download_image(message_id, file_key)

    def add_reaction(self, message_id: str) -> str | None:
        return self._bridge._add_message_reaction(message_id)

    def delete_reaction(self, message_id: str, reaction_id: str) -> bool:
        return self._bridge._delete_message_reaction(message_id, reaction_id)
