"""飞书 API 边界接口。

本模块先定义一层很窄的飞书操作网关，暂不切换生产桥的调用链路。
"""

from __future__ import annotations

import subprocess
import sys
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


@runtime_checkable
class FeishuEventSubscriber(Protocol):
    """飞书事件订阅生命周期边界。"""

    def start(self, *, force: bool = False) -> bool:
        """启动当前配置绑定的事件订阅。"""

    def stop(self) -> bool:
        """停止当前配置绑定的事件订阅。"""

    def restart(self, *, force: bool = False) -> bool:
        """重启当前配置绑定的事件订阅。"""

    def status(self) -> bool:
        """返回当前配置绑定的事件订阅是否健康。"""


class StartWsEventSubscriber:
    """当前 lark-cli/start_ws.py 事件订阅适配器。"""

    def __init__(self, config_path: str | Path, profile: str):
        self.config_path = Path(config_path).expanduser().resolve()
        self.profile = profile
        self.script = Path(__file__).resolve().parents[1] / "start_ws.py"

    def _run(self, action: str, *, force: bool = False) -> bool:
        args = [
            sys.executable,
            str(self.script),
            action,
            "--config",
            str(self.config_path),
            "--profile",
            self.profile,
        ]
        if force:
            args.append("--force")
        result = subprocess.run(
            args,
            cwd=self.script.parent,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def start(self, *, force: bool = False) -> bool:
        return self._run("start", force=force)

    def stop(self) -> bool:
        return self._run("stop")

    def restart(self, *, force: bool = False) -> bool:
        return self._run("restart", force=force)

    def status(self) -> bool:
        return self._run("status")


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
