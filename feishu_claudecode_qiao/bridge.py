"""Bridge: reads Feishu WebSocket events, calls Claude CLI, sends replies.

Design principles:
- No daemon threads, no queue.Queue
- Direct processing: message arrives -> process immediately
- Simple startup: python -m feishu_claudecode_qiao
- Log format matches the legacy version (emoji, separators)
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

from .config import Config, load_config
from .logger import setup_logging
from .security import SecurityPolicy, extract_path_candidates
from .chat_rules import ChatRules
from .message_formatter import auto_detect_format
from .rule_engine import resolve_rule, build_session_key, EffectiveRule, permission_mode_for_profile
from .session_store import SessionStore
from .commands import parse_command
from .audit import AuditLogger

_WORK_DIR = Path(__file__).parent.parent.resolve()
_PROCESSING_REACTION_EMOJI = "OK"


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------


def _is_running(pid_file: Path) -> bool:
    """Check if another bridge instance is already running."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if sys.platform == "win32":
            try:
                import psutil
                proc = psutil.Process(pid)
                return proc.is_running() and "python" in proc.name().lower()
            except ImportError:
                pass
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
            )
            return str(pid) in result.stdout and "python" in result.stdout.lower()
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        pass
    return False


def _write_pid(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid(pid_file: Path) -> None:
    if pid_file.exists():
        pid_file.unlink()


def _stop_bridge(pid_file: Path) -> None:
    """Stop a running bridge instance."""
    if not pid_file.exists():
        print("Bridge is not running (no PID file found).")
        return

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
            )
        else:
            os.kill(pid, 15)  # SIGTERM
        print(f"Bridge stopped (PID {pid}).")
    except Exception as e:
        print(f"Failed to stop bridge: {e}")
    finally:
        if pid_file.exists():
            pid_file.unlink()


def _show_status(pid_file: Path) -> None:
    """Show bridge running status."""
    if _is_running(pid_file):
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        print(f"Bridge is running (PID {pid}).")
    else:
        print("Bridge is not running.")
        if pid_file.exists():
            pid_file.unlink()


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class Bridge:
    """Main bridge: polls events file, calls Claude, sends replies."""

    def __init__(self, config: Config, config_path: str | Path | None = None) -> None:
        self.config = config
        self.config_path = Path(config_path).resolve() if config_path else None
        self.data_dir = Path(config.bridge_data_dir).resolve()
        self.pid_file = self.data_dir / "bridge.pid"
        self.ws_pid_file = self.data_dir / "feishu_ws.pid"
        self.sessions_file = self.data_dir / "sessions.json"
        self.ws_events_file = self.data_dir / "logs" / "feishu_ws_events.jsonl"
        self.images_dir = self.data_dir / "images"
        self.attachments_dir = self.data_dir / "attachments"
        self.bridge_logger, self.msg_logger = setup_logging(
            config.bridge_data_dir,
            config.bridge_log_level,
        )
        self.security = SecurityPolicy(
            permission_mode=config.claude_permission_mode,
            allowed_paths=config.security_allowed_paths,
            blocked_keywords=config.security_blocked_keywords,
            work_dir=config.claude_work_dir,
            data_dir=config.bridge_data_dir,
        )
        self.chat_rules = ChatRules(config.bridge_data_dir)
        self.session_store = SessionStore(self.sessions_file)
        self.session_store.load()
        self.audit = AuditLogger(self.data_dir / "logs" / "audit.jsonl")
        self._token: str | None = None
        self._token_expires = 0.0
        self._processed_ids: set[str] = set()
        self._last_ws_watchdog_check = 0.0
        self._last_ws_watchdog_restart = 0.0
        self._recent_audio_by_chat: dict[str, dict[str, Any]] = {}
        self._recent_files_by_chat: dict[str, dict[str, Any]] = {}
        drive_roots = [Path(f"{chr(letter)}:/") for letter in range(ord("A"), ord("Z") + 1)]
        self._local_file_search_dirs = [
            Path.home() / "Desktop",
            Path.home() / "\u684c\u9762",
            *drive_roots,
        ]

    def _sender_id(self, event_data: dict[str, Any]) -> str:
        sender_id = event_data.get("sender", {}).get("sender_id", {})
        return (
            sender_id.get("user_id")
            or sender_id.get("open_id")
            or sender_id.get("union_id")
            or ""
        )

    def _extract_post_text(self, value: Any) -> str:
        parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("tag") == "text" and node.get("text"):
                    parts.append(str(node["text"]))
                for item in node.values():
                    walk(item)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        return "".join(parts).strip()

    def _extract_post_image_key(self, value: Any) -> str:
        if isinstance(value, dict):
            image_key = value.get("image_key")
            if value.get("tag") == "img" and image_key:
                return str(image_key)
            for item in value.values():
                found = self._extract_post_image_key(item)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._extract_post_image_key(item)
                if found:
                    return found
        return ""

    def _extract_image_key(self, content_obj: Any, content_raw: Any = "") -> str:
        if isinstance(content_obj, dict):
            image_key = content_obj.get("image_key")
            if image_key:
                return str(image_key)
        if isinstance(content_raw, str):
            match = re.search(r"\[Image:\s*([^\]\s]+)\]", content_raw)
            if match:
                return match.group(1)
        return ""

    def _parse_file_xml_content(self, content: str) -> dict[str, str] | None:
        if not content.strip().startswith("<file"):
            return None
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return None
        if root.tag != "file":
            return None
        file_key = root.attrib.get("key") or root.attrib.get("file_key") or ""
        file_name = root.attrib.get("name") or root.attrib.get("file_name") or "unknown"
        if not file_key:
            return None
        return {"file_key": file_key, "file_name": file_name}

    def _cache_recent_audio(
        self,
        chat_id: str,
        message_id: str,
        content_obj: dict[str, Any],
        sender: str = "",
    ) -> None:
        if not chat_id or not message_id:
            return
        self._recent_audio_by_chat[chat_id] = {
            "message_id": message_id,
            "content_obj": dict(content_obj or {}),
            "sender": sender,
            "created_at": time.time(),
        }

    def _cache_recent_file_path(
        self,
        chat_id: str,
        path: str,
        *,
        uploaded: bool = False,
    ) -> None:
        if not chat_id or not path:
            return
        target = Path(path).expanduser().resolve()
        if not target.is_file():
            return
        self._recent_files_by_chat[chat_id] = {
            "files": [str(target)],
            "created_at": time.time(),
            "uploaded": uploaded,
        }

    def _cache_recent_file_message(
        self,
        chat_id: str,
        message_id: str,
        content_obj: dict[str, Any],
        sender: str = "",
    ) -> str:
        if not chat_id or not message_id or not isinstance(content_obj, dict):
            return ""
        file_path = self._process_file(message_id, content_obj)
        if file_path:
            self._cache_recent_file_path(chat_id, file_path)
            recent = self._recent_files_by_chat.get(chat_id)
            if recent is not None:
                recent["message_id"] = message_id
                recent["sender"] = sender
                recent["file_name"] = content_obj.get("file_name", "")
        return file_path or ""

    def _cache_recent_files_from_text(
        self,
        chat_id: str,
        text: str,
        effective_security: SecurityPolicy,
    ) -> None:
        if not chat_id or not text:
            return
        files: list[str] = []
        for candidate in extract_path_candidates(text):
            path = Path(candidate).expanduser().resolve()
            if not path.is_file():
                continue
            if not effective_security.explain_path(path).allowed:
                continue
            path_str = str(path)
            if path_str not in files:
                files.append(path_str)
        if files:
            self._recent_files_by_chat[chat_id] = {
                "files": files,
                "created_at": time.time(),
                "uploaded": False,
            }

    def _file_candidates_from_text(
        self,
        text: str,
        effective_security: SecurityPolicy,
        suffixes: tuple[str, ...] | None = None,
    ) -> list[str]:
        files: list[str] = []
        suffixes = tuple(suffix.lower() for suffix in suffixes or ())
        for candidate in extract_path_candidates(text):
            path = Path(candidate).expanduser().resolve()
            if not path.is_file():
                continue
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            if not effective_security.explain_path(path).allowed:
                continue
            path_str = str(path)
            if path_str not in files:
                files.append(path_str)
        return files

    def _wants_recent_audio(self, content: str) -> bool:
        text = content.lower()
        audio_words = ("\u8bed\u97f3", "\u5f55\u97f3", "voice", "audio")
        recent_words = (
            "\u521a\u624d",
            "\u4e0a\u4e00\u6761",
            "\u524d\u4e00\u6761",
            "\u6700\u8fd1",
            "last",
            "previous",
        )
        return any(word in text for word in audio_words) and any(
            word in text for word in recent_words
        )

    def _is_bare_mention(self, content: str) -> bool:
        text = re.sub(r"@_user_\d+", "", content or "")
        return not text.strip(" \t\r\n:\uFF1A,\uFF0C.\u3002;\uFF1B")

    def _with_group_mention(
        self,
        content: str,
        msg_type: str,
        sender: str,
        sender_name: str = "",
    ) -> str:
        if not sender:
            return content

        if msg_type == "text":
            try:
                data = json.loads(content)
                text = data.get("text", "") if isinstance(data, dict) else content
            except json.JSONDecodeError:
                text = content
            label = html.escape(sender_name or sender, quote=True)
            mention = f'<at user_id="{html.escape(sender, quote=True)}">{label}</at>'
            return json.dumps(
                {"text": f"{mention} {text}".strip()},
                ensure_ascii=False,
                separators=(",", ":"),
            )

        if msg_type == "interactive":
            try:
                card = json.loads(content)
            except json.JSONDecodeError:
                return content
            if not isinstance(card, dict):
                return content
            elements = card.setdefault("elements", [])
            if not isinstance(elements, list):
                return content
            elements.insert(
                0,
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"<at id={html.escape(sender, quote=True)}></at>",
                    },
                },
            )
            return json.dumps(card, ensure_ascii=False, separators=(",", ":"))

        return content

    def _send_event_reply(
        self,
        chat_id: str,
        content: str,
        msg_type: str,
        chat_type: str,
        msg_id: str,
        sender: str,
        sender_name: str,
    ) -> bool:
        if chat_type != "group":
            return self._send_reply(chat_id, content, msg_type)

        reply_content = self._with_group_mention(
            content,
            msg_type,
            sender,
            sender_name,
        )
        return self._send_reply(
            chat_id,
            reply_content,
            msg_type,
            reply_to_message_id=msg_id,
        )

    def _wants_recent_message(self, content: str) -> bool:
        text = content.lower()
        read_words = ("\u8bfb", "\u770b", "\u8bc6\u522b", "read", "check")
        recent_words = (
            "\u521a\u624d",
            "\u4e0a\u4e00\u6761",
            "\u524d\u4e00\u6761",
            "\u6700\u8fd1",
            "last",
            "previous",
        )
        message_words = ("\u6d88\u606f", "\u8fd9\u6761", "message", "msg")
        return (
            any(word in text for word in read_words)
            and any(word in text for word in recent_words)
            and any(word in text for word in message_words)
        )

    def _wants_own_recent_audio(
        self,
        content: str,
        recent: dict[str, Any] | None,
        sender: str,
    ) -> bool:
        if not recent or not sender:
            return False
        if str(recent.get("sender", "")) != sender:
            return False
        return self._is_bare_mention(content) or self._wants_recent_message(content)

    def _recent_audio_context(
        self,
        chat_id: str,
        content: str,
        sender: str = "",
    ) -> str:
        explicit_audio_request = self._wants_recent_audio(content)
        recent = self._recent_audio_by_chat.get(chat_id)
        if recent and time.time() - float(recent.get("created_at", 0)) > 600:
            recent = None
        implicit_own_audio_request = self._wants_own_recent_audio(
            content,
            recent,
            sender,
        )
        if not explicit_audio_request and not implicit_own_audio_request:
            return ""
        if not recent and explicit_audio_request:
            recent = self._fetch_recent_group_media(chat_id, media_type="audio")
            if recent:
                self._cache_recent_audio(
                    chat_id,
                    str(recent.get("message_id", "")),
                    recent.get("content_obj", {}) or {},
                        str(recent.get("sender", "")),
                )
        if not recent:
            return ""

        transcript = self._process_audio(
            str(recent.get("message_id", "")),
            recent.get("content_obj", {}) or {},
        )
        if not transcript:
            return ""
        return (
            "\n\n<bridge_recent_audio_transcript>\n"
            f"{transcript}\n"
            "</bridge_recent_audio_transcript>"
        )

    def _fetch_recent_group_media(
        self,
        chat_id: str,
        media_type: str = "audio",
        page_size: int = 20,
    ) -> dict[str, Any] | None:
        if not chat_id:
            return None

        url = f"{self.config.feishu_domain}/open-apis/im/v1/messages"
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "sort_type": "ByCreateTimeDesc",
            "page_size": page_size,
        }
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                params=params,
                timeout=30,
            )
            result = resp.json()
            if result.get("code") != 0:
                self.bridge_logger.warning(
                    f"Fetch recent group messages failed: {result}"
                )
                return None
            for item in result.get("data", {}).get("items", []) or []:
                msg_type = item.get("msg_type") or item.get("message_type")
                if msg_type != media_type:
                    continue
                content_raw = item.get("body", {}).get("content", "")
                try:
                    content_obj = (
                        json.loads(content_raw)
                        if isinstance(content_raw, str)
                        else content_raw
                    )
                except Exception:
                    content_obj = {}
                if isinstance(content_obj, dict) and content_obj.get("file_key"):
                    return {
                        "message_id": item.get("message_id", ""),
                        "content_obj": content_obj,
                        "sender": item.get("sender", {}).get("id", ""),
                    }
        except Exception as e:
            self.bridge_logger.warning(f"Fetch recent group messages error: {e}")
        return None

    def _append_verified_path_context(self, content: str, candidates: list[str]) -> str:
        if not candidates:
            return content

        lines = ["\n\n<bridge_verified_paths>"]
        for candidate in candidates:
            target = Path(candidate).expanduser().resolve()
            if target.is_file():
                path_type = "file"
            elif target.is_dir():
                path_type = "directory"
            else:
                path_type = "missing"
            lines.append(f"- path: {target}")
            lines.append(f"  type: {path_type}")
        lines.append("</bridge_verified_paths>")
        return content + "\n".join(lines)

    def _extract_local_file_references(self, content: str) -> list[str]:
        refs = extract_path_candidates(content)
        for ref in self._resolve_named_local_files(content):
            if ref not in refs:
                refs.append(ref)
        return refs

    def _resolve_named_local_files(self, content: str) -> list[str]:
        text = content.lower()
        local_markers = (
            "\u684c\u9762",
            "desktop",
            "\u672c\u5730",
            "\u6587\u4ef6",
            "\u6587\u6863",
            "\u539f\u4ef6",
            "\u76d8",
            "file",
            "document",
        )
        if not any(marker in text for marker in local_markers):
            return []

        fragments = re.findall(
            r"[A-Za-z0-9_.-]*(?:feishu|claude|code|qiao)[A-Za-z0-9_.-]*(?:\.[A-Za-z0-9]{1,8})?",
            content,
            flags=re.IGNORECASE,
        )
        resolved: list[str] = []
        for fragment in fragments:
            cleaned = fragment.strip(" .，。；;：:")
            if not cleaned:
                continue
            matches = self._find_named_local_file(cleaned)
            if len(matches) == 1:
                resolved.append(str(matches[0]))
        return resolved

    def _find_named_local_file(self, fragment: str) -> list[Path]:
        matches: list[Path] = []
        lowered = fragment.lower()
        for root in self._local_file_search_dirs:
            if not root.exists() or not root.is_dir():
                continue
            for candidate in root.iterdir():
                if not candidate.is_file():
                    continue
                name = candidate.name.lower()
                stem = candidate.stem.lower()
                if lowered in (name, stem) or lowered in name:
                    matches.append(candidate.resolve())
        return matches

    def _is_upload_to_chat_intent(self, content: str) -> bool:
        text = content.lower()
        action_words = (
            "\u53d1\u9001",
            "\u4e0a\u4f20",
            "\u53d1\u5230",
            "\u4f20\u5230",
            "send",
            "upload",
        )
        target_words = (
            "\u7fa4",
            "\u7fa4\u804a",
            "\u5bf9\u8bdd\u6846",
            "\u804a\u5929",
            "\u8fd9\u91cc",
            "\u5f53\u524d",
            "chat",
            "group",
        )
        file_words = (
            "\u6587\u4ef6",
            "\u6587\u6863",
            "\u539f\u4ef6",
            "file",
            "document",
            "doc",
        )
        return (
            any(word in text for word in action_words)
            and any(word in text for word in target_words)
            and any(word in text for word in file_words)
        )

    def _is_send_local_file_intent(self, content: str) -> bool:
        text = content.lower()
        local_words = (
            "\u684c\u9762",
            "\u672c\u5730",
            "\u751f\u6210",
            "\u8def\u5f84",
            "desktop",
            "local",
            "c:",
            "d:",
            "\u76d8",
        )
        return self._is_upload_to_chat_intent(content) and any(
            word in text for word in local_words
        )

    def _is_recent_generated_file_upload_intent(self, content: str) -> bool:
        text = content.lower()
        action_words = (
            "\u53d1",
            "\u53d1\u9001",
            "\u4e0a\u4f20",
            "\u53d1\u4e0a\u6765",
            "\u53d1\u6765",
            "send",
            "upload",
        )
        recent_words = (
            "\u751f\u6210",
            "\u521a\u624d",
            "\u4e0a\u4e00\u4e2a",
            "\u4e0a\u4e00\u6761",
            "\u7ed3\u679c",
            "\u8868\u683c",
            "excel",
            "xlsx",
            "result",
            "generated",
        )
        file_words = (
            "\u6587\u4ef6",
            "\u6587\u6863",
            "\u8868\u683c",
            "file",
            "document",
            "excel",
            "xlsx",
        )
        return (
            any(word in text for word in action_words)
            and any(word in text for word in recent_words)
            and any(word in text for word in file_words)
        )

    def _is_new_table_generation_intent(self, content: str) -> bool:
        text = content.lower()
        transform_words = (
            "\u6c47\u603b",
            "\u6574\u7406",
            "\u5408\u5e76",
            "\u91cd\u65b0",
            "\u6700\u65b0",
            "\u65b0\u8868",
            "\u65b0\u7248",
            "\u66f4\u65b0",
            "summarize",
            "merge",
            "regenerate",
            "latest",
            "new",
            "updated",
        )
        table_words = (
            "\u8868\u683c",
            "excel",
            "xlsx",
            "xls",
            "csv",
        )
        return any(word in text for word in transform_words) and any(
            word in text for word in table_words
        )

    def _wants_recent_file_context(self, content: str) -> bool:
        text = content.lower()
        if self._is_bare_mention(content):
            return True
        action_words = (
            "\u5206\u6790",
            "\u770b",
            "\u8bfb",
            "\u603b\u7ed3",
            "\u63d0\u70bc",
            "\u6ce8\u610f",
            "analyze",
            "read",
            "summarize",
            "check",
        )
        file_words = (
            "\u6587\u4ef6",
            "\u6587\u6863",
            "\u9644\u4ef6",
            "\u521a\u624d",
            "\u4e0a\u4e00\u4e2a",
            "file",
            "document",
            "attachment",
        )
        task_words = (
            "\u7269\u6d41\u7801",
            "\u67e5\u8be2",
            "\u8868\u683c",
            "excel",
            "xlsx",
            "xls",
        )
        if any(word in text for word in task_words):
            return True
        return any(word in text for word in action_words) and any(
            word in text for word in file_words
        )

    def _recent_file_context(
        self,
        chat_id: str,
        content: str,
        effective_security: SecurityPolicy,
    ) -> str:
        if not self._wants_recent_file_context(content):
            return ""
        recent = self._recent_files_by_chat.get(chat_id)
        if not recent:
            return ""
        if time.time() - float(recent.get("created_at", 0)) > 1800:
            self._recent_files_by_chat.pop(chat_id, None)
            return ""
        lines = ["\n\n<bridge_recent_file>"]
        added = False
        for candidate in recent.get("files", []) or []:
            path = Path(str(candidate)).expanduser().resolve()
            if not path.is_file():
                continue
            if not effective_security.explain_path(path).allowed:
                continue
            lines.append(f"- path: {path}")
            lines.append("  type: file")
            added = True
        lines.append("</bridge_recent_file>")
        return "\n".join(lines) if added else ""

    def _file_tool_hint(self, path: str) -> str:
        suffix = Path(path).suffix.lower()
        if suffix == ".pdf":
            tools = "Python pypdf or pdfplumber"
        elif suffix in (".docx", ".doc"):
            tools = "Python python-docx"
        elif suffix in (".xlsx", ".xls", ".csv"):
            tools = "Python openpyxl or pandas"
        elif suffix in (".pptx", ".ppt"):
            tools = "Python python-pptx"
        elif suffix in (".txt", ".md", ".json", ".xml", ".html", ".csv"):
            tools = "direct text reading"
        elif suffix in (".zip", ".7z", ".rar"):
            tools = "archive listing/extraction tools, then read extracted files"
        elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"):
            tools = "Claude Code image understanding or local OCR/image tools"
        elif suffix in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv", ".m4v"):
            tools = "ffprobe/ffmpeg for metadata, keyframes, thumbnails, and audio extraction"
        else:
            tools = "available local command-line tools or Python libraries"
        return (
            "\n\n<bridge_file_tool_hint>\n"
            f"- file: {Path(path).expanduser().resolve()}\n"
            f"- preferred_reader: {tools}\n"
            "- instruction: Use local Python libraries or lightweight text extraction first. "
            "For images, inspect the local image directly or use OCR/image tooling when needed. Do not rely on pdftoppm as the first option for PDFs; for videos, use ffprobe/ffmpeg directly to inspect metadata, extract a few representative frames, or extract audio when needed. If one tool is missing, try another available local reader.\n"
            "</bridge_file_tool_hint>"
        )

    def _append_file_tool_hints(self, content: str) -> str:
        hinted: list[str] = []
        for candidate in extract_path_candidates(content):
            path = Path(candidate).expanduser().resolve()
            if not path.is_file():
                continue
            path_str = str(path)
            if path_str in hinted:
                continue
            hinted.append(path_str)
            content += self._file_tool_hint(path_str)
        return content

    def _is_auto_upload_generated_table_intent(self, content: str) -> bool:
        text = content.lower()
        query_words = (
            "bi",
            "\u67e5bi",
            "\u67e5\u8be2bi",
            "\u7269\u6d41\u7801",
            "\u67e5\u8be2",
            "\u67e5",
            "query",
            "search",
        )
        table_words = (
            "\u8868\u683c",
            "excel",
            "xlsx",
            "xls",
            "csv",
        )
        return any(word in text for word in query_words) or any(
            word in text for word in table_words
        )

    def _maybe_upload_generated_table_from_reply(
        self,
        chat_id: str,
        reply_to_message_id: str,
        user_content: str,
        claude_reply: str,
        effective_security: SecurityPolicy,
    ) -> str:
        if not self._is_auto_upload_generated_table_intent(user_content):
            return ""
        candidates = self._file_candidates_from_text(
            claude_reply,
            effective_security,
            suffixes=(".xlsx", ".xls", ".csv"),
        )
        if len(candidates) != 1:
            return ""
        path = candidates[0]
        if self._send_local_file(chat_id, path, reply_to_message_id=reply_to_message_id):
            recent = self._recent_files_by_chat.get(chat_id)
            if recent and path in [str(item) for item in recent.get("files", [])]:
                recent["uploaded"] = True
            return path
        return ""

    def _maybe_upload_recent_file(
        self,
        chat_id: str,
        reply_to_message_id: str,
        user_content: str,
        effective_security: SecurityPolicy,
    ) -> str:
        if self._is_new_table_generation_intent(user_content):
            return ""
        if not self._is_recent_generated_file_upload_intent(user_content):
            return ""
        recent = self._recent_files_by_chat.get(chat_id)
        if not recent:
            return ""
        if recent.get("uploaded"):
            return ""
        if time.time() - float(recent.get("created_at", 0)) > 1800:
            self._recent_files_by_chat.pop(chat_id, None)
            return ""
        files = [str(path) for path in recent.get("files", []) if path]
        for candidate in reversed(files):
            path = Path(candidate).expanduser().resolve()
            if not path.is_file():
                continue
            if not effective_security.explain_path(path).allowed:
                continue
            if self._send_local_file(chat_id, str(path), reply_to_message_id=reply_to_message_id):
                recent["uploaded"] = True
                return str(path)
        return ""

    def _recent_uploaded_file_for_intent(
        self,
        chat_id: str,
        user_content: str,
        effective_security: SecurityPolicy,
    ) -> str:
        if self._is_new_table_generation_intent(user_content):
            return ""
        if not self._is_recent_generated_file_upload_intent(user_content):
            return ""
        recent = self._recent_files_by_chat.get(chat_id)
        if not recent or not recent.get("uploaded"):
            return ""
        if time.time() - float(recent.get("created_at", 0)) > 1800:
            self._recent_files_by_chat.pop(chat_id, None)
            return ""
        for candidate in reversed([str(path) for path in recent.get("files", []) if path]):
            path = Path(candidate).expanduser().resolve()
            if path.is_file() and effective_security.explain_path(path).allowed:
                return str(path)
        return ""

    def _maybe_upload_file_from_claude_reply(
        self,
        chat_id: str,
        reply_to_message_id: str,
        user_content: str,
        claude_reply: str,
        effective_security: SecurityPolicy,
    ) -> str:
        if not self._is_upload_to_chat_intent(user_content):
            return ""

        candidates: list[str] = []
        for candidate in extract_path_candidates(claude_reply):
            if candidate not in candidates:
                candidates.append(candidate)

        for candidate in candidates:
            path = Path(candidate).expanduser().resolve()
            if not path.is_file():
                continue
            if not effective_security.explain_path(path).allowed:
                continue
            if self._send_local_file(chat_id, str(path), reply_to_message_id=reply_to_message_id):
                return str(path)
        return ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _ws_pid_running(self) -> bool:
        if not self.ws_pid_file.exists():
            return False
        try:
            pid = int(self.ws_pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        if sys.platform == "win32":
            try:
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _check_websocket_watchdog(self, *, force: bool = False) -> None:
        interval = int(getattr(self.config, "bridge_ws_watchdog_interval_seconds", 30) or 0)
        if interval <= 0:
            return
        now = time.time()
        if not force and now - self._last_ws_watchdog_check < interval:
            return
        self._last_ws_watchdog_check = now

        if self._ws_pid_running():
            return

        if not force and now - self._last_ws_watchdog_restart < max(interval, 60):
            return
        self._last_ws_watchdog_restart = now

        config_arg = str(self.config_path or Path("config.toml").resolve())
        profile = getattr(self.config, "bridge_ws_profile", "qiao-test") or "qiao-test"
        script = _WORK_DIR / "start_ws.py"
        args = [
            sys.executable,
            str(script),
            "start",
            "--config",
            config_arg,
            "--profile",
            profile,
            "--force",
        ]
        self.bridge_logger.warning(
            f"WebSocket subscriber is not running; starting profile={profile}"
        )
        result = subprocess.run(
            args,
            cwd=_WORK_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            self.bridge_logger.info(
                f"WebSocket subscriber restarted by watchdog: {result.stdout.strip()}"
            )
        else:
            self.bridge_logger.error(
                "WebSocket subscriber watchdog start failed: "
                f"code={result.returncode} stdout={result.stdout[:500]} stderr={result.stderr[:500]}"
            )

    def run(self) -> None:
        """Main loop: read events file -> process -> sleep."""
        self.bridge_logger.info("=" * 50)
        self.bridge_logger.info("Bridge starting...")
        self.bridge_logger.info("=" * 50)
        self.bridge_logger.info("Bridge running. Press Ctrl+C to stop.")
        self.bridge_logger.info("=" * 50)

        self.bridge_logger.info(f"Loaded {len(self.session_store._data)} sessions from store")

        # Start reading only new events. Replaying old lines can resend stale replies.
        last_size = self._initial_event_offset()
        if self.ws_events_file.exists():
            self.bridge_logger.info(
                f"Watching events file: {self.ws_events_file} "
                f"(starting at offset {last_size})"
            )
        else:
            self.bridge_logger.info(
                f"Events file not found yet: {self.ws_events_file}"
            )

        try:
            while True:
                self._check_websocket_watchdog()
                if self.ws_events_file.exists():
                    current_size = self.ws_events_file.stat().st_size
                    if current_size > last_size:
                        with open(
                            self.ws_events_file, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            f.seek(last_size)
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    event = json.loads(line)
                                    event = self._normalize_event(event)
                                    msg_id = (
                                        event.get("event", {})
                                        .get("message", {})
                                        .get("message_id", "")
                                    )
                                    if msg_id and msg_id in self._processed_ids:
                                        continue
                                    if msg_id:
                                        self._processed_ids.add(msg_id)
                                    self._process_event(event)
                                except json.JSONDecodeError:
                                    self.bridge_logger.debug(
                                        f"Skip invalid JSON line: {line[:80]}"
                                    )
                            last_size = f.tell()
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.bridge_logger.info("Stopping...")
        finally:
            self._save_sessions()
            _remove_pid(self.pid_file)
            self.bridge_logger.info("Bridge stopped.")

    def _initial_event_offset(self) -> int:
        if not self.ws_events_file.exists():
            return 0
        return self.ws_events_file.stat().st_size

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalize event structure from different WebSocket sources."""
        # Some event sources wrap the event under "data"
        if "data" in event and "event" not in event:
            event = event["data"]
        # lark-cli --compact emits a flat NDJSON object. Convert it back to
        # the nested Feishu shape used by the bridge.
        if "event" not in event and event.get("type") == "im.message.receive_v1":
            content = event.get("content", "")
            message_type = event.get("message_type", "text")
            if message_type == "text":
                content = json.dumps({"text": content}, ensure_ascii=False)
            elif message_type == "file" and isinstance(content, str):
                file_info = self._parse_file_xml_content(content)
                if file_info:
                    content = json.dumps(file_info, ensure_ascii=False)
            return {
                "event": {
                    "sender": {
                        "sender_id": {
                            "user_id": event.get("sender_id", ""),
                            "name": event.get("sender_name", ""),
                        }
                    },
                    "message": {
                        "message_id": event.get("message_id") or event.get("id", ""),
                        "chat_type": event.get("chat_type", ""),
                        "chat_id": event.get("chat_id", ""),
                        "message_type": message_type,
                        "content": content,
                    },
                }
            }
        return event

    def _process_event(self, event: dict[str, Any]) -> None:
        """Process an event with a temporary Feishu reaction on the source message."""
        event_data = event.get("event", {})
        message = event_data.get("message", {})

        msg_id = message.get("message_id", "")
        chat_type = message.get("chat_type", "")
        chat_id = message.get("chat_id", "")
        msg_type = message.get("message_type", "text")
        content_raw = message.get("content", "")
        try:
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            content = content_obj.get("text", "") if isinstance(content_obj, dict) else ""
        except Exception:
            content = content_raw if isinstance(content_raw, str) else ""

        sender = self._sender_id(event_data)
        if sender == self.config.feishu_app_id:
            self._process_event_body(event)
            return

        if msg_type == "audio":
            if isinstance(content_obj, dict):
                self._cache_recent_audio(chat_id, msg_id, content_obj, sender)
        elif msg_type == "file":
            if isinstance(content_obj, dict):
                self._cache_recent_file_message(chat_id, msg_id, content_obj, sender)

        if chat_type == "group" and self.config.bridge_require_mention_in_group:
            bot_name = self.config.bridge_bot_display_name or "bot"
            mentions = message.get("mentions", [])
            if not self._is_mentioned(content, bot_name, mentions):
                self._process_event_body(event)
                return

        reaction_id = self._add_message_reaction(msg_id) if msg_id else None
        try:
            self._process_event_body(event)
        finally:
            if msg_id and reaction_id:
                self._delete_message_reaction(msg_id, reaction_id)

    def _process_event_body(self, event: dict[str, Any]) -> None:
        """Process a single Feishu event."""
        event_data = event.get("event", {})
        message = event_data.get("message", {})

        msg_id = message.get("message_id", "")
        chat_type = message.get("chat_type", "")
        chat_id = message.get("chat_id", "")
        msg_type = message.get("message_type", "text")
        content_raw = message.get("content", "")

        # Parse content JSON
        try:
            content_obj = (
                json.loads(content_raw)
                if isinstance(content_raw, str)
                else content_raw
            )
            if msg_type == "post":
                content = self._extract_post_text(content_obj)
            else:
                content = content_obj.get("text", "")
        except Exception:
            content_obj = {}
            content = content_raw if isinstance(content_raw, str) else ""

        sender = self._sender_id(event_data)
        sender_name = (
            event_data.get("sender", {})
            .get("sender_id", {})
            .get("name", "")
            or sender[:12]
            or "用户"
        )

        def reply(reply_content: str, reply_msg_type: str = "text") -> bool:
            return self._send_event_reply(
                chat_id,
                reply_content,
                reply_msg_type,
                chat_type,
                msg_id,
                sender,
                sender_name,
            )

        # Log incoming message
        self.msg_logger.info("=" * 50)
        self.msg_logger.info(f"📩 [{chat_type}] {sender_name} @ {chat_id}")
        self.msg_logger.info(f"内容: {content[:200]}")
        self.audit.write("message_received", chat_id=chat_id, sender=sender, sender_name=sender_name, msg_type=msg_type)

        # Skip bot's own messages
        if sender == self.config.feishu_app_id:
            self.msg_logger.debug("Skip bot's own message")
            return

        # Group mention check
        if chat_type == "group" and self.config.bridge_require_mention_in_group:
            bot_name = self.config.bridge_bot_display_name or "bot"
            mentions = message.get("mentions", [])
            if not self._is_mentioned(content, bot_name, mentions):
                self.msg_logger.debug("Bot not mentioned in group, skipping")
                return

        # Resolve rules
        rule_exists = self.chat_rules.exists(chat_id)
        chat_rule = self.chat_rules.get(chat_id)
        effective_rule = resolve_rule(chat_rule, sender_id=sender)
        if chat_type != "group" and not rule_exists:
            effective_rule = resolve_rule(
                chat_rule,
                sender_id=sender,
                temporary={
                    "permission_profile": self.config.bridge_personal_permission_profile,
                },
            )
        effective_security = self._security_for_rule(effective_rule)

        # Security check (after rule resolution)
        is_blocked, warning = effective_security.check_message(content)
        if is_blocked:
            self.msg_logger.warning(f"Message blocked: {warning}")
            reply(warning)
            return

        # Risky intent check
        risk = effective_security.check_risky_intent(content)
        if risk.risky:
            policy = effective_rule.get("confirm_policy", {})
            action = policy.get(risk.category, "confirm")
            if action == "deny":
                self.audit.write("risk_denied", chat_id=chat_id, sender=sender, category=risk.category, reason=risk.reason)
                reply(f"已拒绝：{risk.reason}")
                return
            if action == "confirm":
                self.audit.write("permission_required", chat_id=chat_id, sender=sender, category=risk.category, reason=risk.reason)
                reply(f"需要确认后继续：{risk.reason}\n请按当前聊天规则确认授权后再发送。")
                return
            self.audit.write("risk_allowed", chat_id=chat_id, sender=sender, category=risk.category, reason=risk.reason)

        # Check paths in message content before calling Claude
        allowed_path_candidates: list[str] = []
        for candidate in self._extract_local_file_references(content):
            result = effective_security.explain_path(candidate)
            if not result.allowed:
                self.audit.write(
                    "path_rejected",
                    chat_id=chat_id,
                    sender=sender,
                    path=candidate,
                    reason=result.reason,
                    matched_pattern=result.matched_pattern,
                )
                reply(
                    f"路径不允许访问：{candidate}\n原因：{result.reason}",
                )
                return
            allowed_path_candidates.append(candidate)

        session_key = build_session_key(chat_id, sender, effective_rule.get("session_mode", "shared_chat"))

        uploaded_recent_file = self._maybe_upload_recent_file(
            chat_id,
            msg_id if chat_type == "group" else "",
            content,
            effective_security,
        )
        if uploaded_recent_file:
            self._send_event_reply(
                chat_id,
                f"\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1a{Path(uploaded_recent_file).name}",
                "text",
                chat_type,
                msg_id,
                sender,
                sender_name,
            )
            self.msg_logger.info(f"\u2705 \u6587\u4ef6\u5df2\u4e0a\u4f20: {uploaded_recent_file}")
            self.audit.write(
                "local_file_sent",
                chat_id=chat_id,
                sender=sender,
                path=uploaded_recent_file,
                success=True,
            )
            return

        already_uploaded_recent_file = self._recent_uploaded_file_for_intent(
            chat_id,
            content,
            effective_security,
        )
        if already_uploaded_recent_file:
            self._send_event_reply(
                chat_id,
                f"\u521a\u624d\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1a{Path(already_uploaded_recent_file).name}",
                "text",
                chat_type,
                msg_id,
                sender,
                sender_name,
            )
            self.audit.write(
                "local_file_already_sent",
                chat_id=chat_id,
                sender=sender,
                path=already_uploaded_recent_file,
                success=True,
            )
            return

        if allowed_path_candidates and self._is_send_local_file_intent(content):
            file_candidates = [
                str(Path(candidate).expanduser().resolve())
                for candidate in allowed_path_candidates
                if Path(candidate).expanduser().resolve().is_file()
            ]
            if len(file_candidates) == 1:
                sent = self._send_local_file(
                    chat_id,
                    file_candidates[0],
                    reply_to_message_id=msg_id if chat_type == "group" else "",
                )
                self.audit.write(
                    "local_file_sent",
                    chat_id=chat_id,
                    sender=sender,
                    path=file_candidates[0],
                    success=sent,
                )
                if not sent:
                    reply(
                        f"\u6587\u4ef6\u4e0a\u4f20\u5931\u8d25\uff1a{file_candidates[0]}",
                    )
                return
            if len(file_candidates) > 1:
                reply(
                    "\u627e\u5230\u591a\u4e2a\u6587\u4ef6\uff0c\u8bf7\u8865\u5145\u66f4\u7cbe\u786e\u7684\u6587\u4ef6\u540d\u6216\u76f4\u63a5\u53d1\u9001\u5b8c\u6574\u8def\u5f84\u3002",
                )
                return

        # Handle commands
        cmd = parse_command(content)
        if not cmd.is_command:
            cmd = self._natural_rule_command(content, chat_type) or cmd
        if cmd.is_command:
            command_reply = self._handle_command(cmd, effective_rule, session_key, chat_id, sender, sender_name, chat_rule, chat_type)
            self._send_event_reply(chat_id, command_reply, "text", chat_type, msg_id, sender, sender_name)
            return

        onboarding_requested = cmd.is_command or any(
            word in content for word in ("规则", "设置", "权限", "命令", "帮助", "workspace", "allowed_paths")
        )
        if chat_type == "group" and onboarding_requested and not rule_exists and not chat_rule.get("onboarding_shown"):
            self.chat_rules.set(chat_id, onboarding_shown=True)
            self._send_event_reply(
                chat_id,
                self._cmd_group_onboarding(),
                "text",
                chat_type,
                msg_id,
                sender,
                sender_name,
            )

        content = self._append_verified_path_context(content, allowed_path_candidates)

        recent_audio_context = self._recent_audio_context(chat_id, content, sender)
        if recent_audio_context:
            content += recent_audio_context

        recent_file_context = self._recent_file_context(
            chat_id,
            content,
            effective_security,
        )
        if recent_file_context:
            content += recent_file_context

        # Check rollover BEFORE getting session_id
        rollover_summary = ""
        if session_key:
            rollover_summary = self._maybe_rollover_session(session_key, effective_rule)

        # Get session_id after rollover (may have been cleared)
        session_id = self.session_store.get(session_key).session_id if session_key else None
        if not session_id:
            session_id = None

        # Handle media messages
        img_path: str | None = None
        if msg_type == "image":
            img_path = self._download_image(
                msg_id, self._extract_image_key(content_obj, content_raw)
            )
            if img_path:
                self._cache_recent_file_path(chat_id, img_path)
            content = f"[图片] {img_path or ''}"
            self.msg_logger.info(f"Image downloaded: {img_path}")
        elif msg_type == "audio":
            transcribed = self._process_audio(msg_id, content_obj)
            if transcribed:
                content = transcribed
                self.msg_logger.info(f"Audio transcribed: {transcribed[:100]}...")
            else:
                content = "[语音消息]"
        elif msg_type == "file":
            recent = self._recent_files_by_chat.get(chat_id)
            recent_files = [str(path) for path in (recent or {}).get("files", [])]
            file_info = recent_files[-1] if recent_files else self._process_file(msg_id, content_obj)
            if file_info:
                self._cache_recent_file_path(chat_id, file_info)
            content = f"[文件] {file_info or ''}"
        elif msg_type == "post":
            image_key = self._extract_post_image_key(content_obj) or self._extract_image_key(content_obj, content_raw)
            if image_key:
                img_path = self._download_image(msg_id, image_key)
                if img_path:
                    self._cache_recent_file_path(chat_id, img_path)
                self.msg_logger.info(f"Post image downloaded: {img_path}")
            post_text = self._extract_post_text(content_obj)
            if not post_text and isinstance(content_raw, str):
                post_text = re.sub(r"\[Image:\s*[^\]\s]+\]", "", content_raw).strip()
            content = post_text or "[富文本消息]"
            if img_path:
                content = f"{content}\n[图片] {img_path}"

        # Build prompt with rollover summary
        content = self._append_file_tool_hints(content)
        content_for_prompt = content
        if rollover_summary:
            content_for_prompt = f"{rollover_summary}\n\n当前用户消息:\n{content}"

        # Call Claude and send reply
        try:
            prompt = self._build_prompt(chat_id, sender_name, content_for_prompt, effective_rule)

            effective_workspace = effective_rule.get("workspace") or self.config.claude_work_dir
            permission_mode = permission_mode_for_profile(
                effective_rule.get("permission_profile", ""),
                fallback=self.config.claude_permission_mode,
            )

            reply, new_session = self._call_claude(
                prompt,
                session_id,
                cwd=effective_workspace,
                permission_mode=permission_mode,
            )
            if (
                session_key
                and session_id
                and self._is_missing_claude_session_reply(reply)
            ):
                self.bridge_logger.warning(
                    f"Claude session missing, retrying without session: {session_id}"
                )
                self.session_store.update_session_id(session_key, "")
                reply, new_session = self._call_claude(
                    prompt,
                    None,
                    cwd=effective_workspace,
                    permission_mode=permission_mode,
                )
            if session_key and new_session:
                self.session_store.update_session_id(session_key, new_session)
            if session_key:
                self.session_store.record_turn(session_key, len(prompt), len(reply), attachment_task=bool(img_path or msg_type in ("audio", "file")))

            self._cache_recent_files_from_text(chat_id, reply, effective_security)

            uploaded_generated_table = self._maybe_upload_generated_table_from_reply(
                chat_id,
                msg_id if chat_type == "group" else "",
                content,
                reply,
                effective_security,
            )
            if uploaded_generated_table:
                self._send_event_reply(
                    chat_id,
                    f"\u67e5\u8be2\u5b8c\u6210\uff0c\u5df2\u4e0a\u4f20\u6587\u4ef6\uff1a{Path(uploaded_generated_table).name}",
                    "text",
                    chat_type,
                    msg_id,
                    sender,
                    sender_name,
                )
                self.msg_logger.info(f"\u2705 \u6587\u4ef6\u5df2\u4e0a\u4f20: {uploaded_generated_table}")
                self.audit.write(
                    "local_file_sent",
                    chat_id=chat_id,
                    sender=sender,
                    path=uploaded_generated_table,
                    success=True,
                )
                return

            uploaded_reply_file = self._maybe_upload_file_from_claude_reply(
                chat_id,
                msg_id if chat_type == "group" else "",
                content,
                reply,
                effective_security,
            )
            if uploaded_reply_file:
                self._send_event_reply(
                    chat_id,
                    f"已上传文件：{Path(uploaded_reply_file).name}",
                    "text",
                    chat_type,
                    msg_id,
                    sender,
                    sender_name,
                )
                self.msg_logger.info(f"✅ 文件已上传: {uploaded_reply_file}")
                self.audit.write(
                    "local_file_sent",
                    chat_id=chat_id,
                    sender=sender,
                    path=uploaded_reply_file,
                    success=True,
                )
                return

            content_str, msg_fmt = auto_detect_format(reply)
            self._send_event_reply(chat_id, content_str, msg_fmt, chat_type, msg_id, sender, sender_name)

            self.msg_logger.info(f"✅ 回复已发送 ({len(reply)} chars)")
            self.msg_logger.info("=" * 50)
            self.audit.write("reply_sent", chat_id=chat_id, sender=sender, session_key=session_key, msg_type=msg_fmt)

        except Exception as e:
            self.bridge_logger.exception(f"处理消息失败: {e}")
            reply(
                f"处理消息时出错: {e}",
            )

    def _can_modify_chat_rule(
        self,
        effective_rule: EffectiveRule,
        sender: str,
        chat_type: str,
    ) -> bool:
        if chat_type != "group":
            return True
        bot_admins = self.config.bridge_bot_admins or []
        if bot_admins:
            return sender in bot_admins
        return bool(self.config.bridge_bot_owner_id) and sender == self.config.bridge_bot_owner_id

    def _natural_rule_command(self, content: str, chat_type: str):
        if chat_type != "group":
            return None
        text = content.strip()
        if not text or text.startswith("/"):
            return None

        permission_match = re.search(r"(?:权限|permission).*?(readonly|safe|dev|admin|stateless)", text, re.IGNORECASE)
        if permission_match:
            from .commands import Command
            return Command(name="permission", args=f"set {permission_match.group(1).lower()}", is_command=True)
        if any(word in text for word in ("批准权限", "批权限", "最大权限", "授权", "批准")):
            from .commands import Command
            return Command(name="permission", args="set admin", is_command=True)

        if any(word in text for word in ("访问权限", "访问目录", "可访问", "放行", "允许访问")):
            candidates = extract_path_candidates(text)
            drive_match = re.search(r"([A-Za-z])\s*盘", text)
            if drive_match:
                candidates.append(f"{drive_match.group(1).upper()}:/")
            if candidates:
                from .commands import Command
                unique = []
                for candidate in candidates:
                    if candidate not in unique:
                        unique.append(candidate)
                return Command(name="paths", args="add " + ", ".join(unique), is_command=True)
        return None

    def _handle_command(self, cmd, effective_rule, session_key, chat_id, sender, sender_name, chat_rule, chat_type=""):
        if cmd.name == "help":
            return self._cmd_help()
        elif cmd.name == "rules":
            return self._cmd_rules(effective_rule)
        elif cmd.name == "context":
            return self._cmd_context(session_key)
        elif cmd.name == "summary":
            return self._cmd_summary(session_key)
        elif cmd.name == "ask":
            return self._cmd_ask(chat_id, sender, sender_name, cmd.args, chat_rule)
        elif cmd.name == "reset":
            if session_key:
                self.session_store.clear_session(session_key)
            return "当前会话已重置。"
        elif cmd.name == "new":
            if session_key:
                self.session_store.update_session_id(session_key, "")
            return "已开启新会话。"
        elif cmd.name == "compact":
            summary = self._maybe_rollover_session(session_key, effective_rule, force=True)
            return "已生成交接摘要并开启新会话。" if summary else "无法生成交接摘要。"
        elif cmd.name == "workspace":
            return self._cmd_workspace(
                chat_id, cmd.args, effective_rule,
                can_modify=self._can_modify_chat_rule(effective_rule, sender, chat_type),
            )
        elif cmd.name == "paths":
            return self._cmd_paths(
                chat_id, cmd.args, effective_rule,
                can_modify=self._can_modify_chat_rule(effective_rule, sender, chat_type),
            )
        elif cmd.name == "permission":
            return self._cmd_permission(
                chat_id, cmd.args, effective_rule,
                can_modify=self._can_modify_chat_rule(effective_rule, sender, chat_type),
            )
        return f"未知命令: /{cmd.name}"

    def _strip_trailing_mentions(self, value: str) -> str:
        value = re.sub(r"\s+@_user_\d+\s*$", "", value.strip())
        value = re.sub(r"\s+@[^\s,;，；]+\s*$", "", value).strip()
        return value

    def _cmd_workspace(self, chat_id: str, args: str, effective_rule: EffectiveRule, *, can_modify: bool = True) -> str:
        if not args:
            return f"当前 workspace: {effective_rule.get('workspace') or self.config.claude_work_dir or '(未设置)'}"
        action, _, value = args.partition(" ")
        value = self._strip_trailing_mentions(value)
        if action == "set" and value.strip():
            if not can_modify:
                return "拒绝修改规则：你没有当前聊天的规则管理权限。"
            target = Path(value.strip()).expanduser().resolve()
            if not target.exists():
                return f"拒绝设置 workspace：路径不存在: {target}"
            if not target.is_dir():
                return f"拒绝设置 workspace：路径不是目录: {target}"

            check = self.security.explain_path(target)
            if not check.allowed:
                return f"拒绝设置 workspace：{check.reason}"

            self.chat_rules.set(chat_id, workspace=str(target), allowed_paths=[str(target)])
            return f"已设置 workspace 并放行路径: {target}"
        if action == "clear":
            if not can_modify:
                return "拒绝修改规则：你没有当前聊天的规则管理权限。"
            self.chat_rules.set(chat_id, workspace="")
            return "已清空 workspace。"
        return "用法: /workspace | /workspace set <path> | /workspace clear"

    def _split_path_args(self, value: str) -> list[str]:
        value = self._strip_trailing_mentions(value)
        return [item.strip().strip('"') for item in re.split(r"[\n,;，；]+", value) if item.strip()]

    def _validate_rule_path(self, value: str) -> tuple[Path | None, str]:
        target = Path(value.strip()).expanduser().resolve()
        if not target.exists():
            return None, f"路径不存在: {target}"
        if not target.is_dir():
            return None, f"路径不是目录: {target}"
        check = self.security.explain_path(target)
        if not check.allowed:
            return None, f"路径不允许: {check.reason}"
        return target, ""

    def _cmd_paths(self, chat_id: str, args: str, effective_rule: EffectiveRule, *, can_modify: bool = True) -> str:
        current = [str(p) for p in (effective_rule.get("allowed_paths", []) or []) if str(p).strip()]
        if not args:
            if not current:
                return "当前 allowed_paths: (未设置)\n用法: /paths add <目录1>, <目录2> | /paths set <目录1>, <目录2> | /paths clear"
            lines = ["当前 allowed_paths:"]
            lines.extend(f"- {path}" for path in current)
            return "\n".join(lines)

        action, _, value = args.partition(" ")
        action = action.strip().lower()
        if action == "clear":
            if not can_modify:
                return "拒绝修改规则：你没有当前聊天的规则管理权限。"
            self.chat_rules.set(chat_id, allowed_paths=[])
            return "已清空 allowed_paths。"

        if action not in {"add", "set"} or not value.strip():
            return "用法: /paths add <目录1>, <目录2> | /paths set <目录1>, <目录2> | /paths clear"
        if not can_modify:
            return "拒绝修改规则：你没有当前聊天的规则管理权限。"

        accepted: list[str] = []
        errors: list[str] = []
        for raw in self._split_path_args(value):
            target, error = self._validate_rule_path(raw)
            if target is None:
                errors.append(error)
                continue
            path_str = str(target)
            if path_str not in accepted:
                accepted.append(path_str)

        if errors:
            return "路径设置失败：\n" + "\n".join(f"- {error}" for error in errors)
        if action == "add":
            merged = list(current)
            for path_str in accepted:
                if path_str not in merged:
                    merged.append(path_str)
            accepted = merged

        self.chat_rules.set(chat_id, allowed_paths=accepted)
        lines = ["已设置 allowed_paths:"]
        lines.extend(f"- {path}" for path in accepted)
        return "\n".join(lines)

    def _permission_label(self, profile: str) -> str:
        labels = {
            "readonly": "只读",
            "safe": "安全",
            "dev": "开发",
            "admin": "最大权限",
            "stateless": "无上下文",
        }
        return f"{profile}（{labels.get(profile, '未知')}）"

    def _cmd_permission(self, chat_id: str, args: str, effective_rule: EffectiveRule, *, can_modify: bool = True) -> str:
        if not args:
            return f"当前 permission_profile: {self._permission_label(effective_rule.get('permission_profile'))}"
        action, _, value = args.partition(" ")
        value = value.strip()
        if action == "set" and value in {"readonly", "safe", "dev", "admin", "stateless"}:
            if not can_modify:
                return "拒绝修改规则：你没有当前聊天的规则管理权限。"
            self.chat_rules.set(chat_id, permission_profile=value)
            return f"已设置 permission_profile: {self._permission_label(value)}"
        return "用法: /permission | /permission set <readonly|safe|dev|admin|stateless>\n档位: readonly（只读）, safe（安全）, dev（开发）, admin（最大权限）, stateless（无上下文）"

    def _cmd_help(self) -> str:
        return """可用命令：
/help - 显示帮助
/rules - 查看当前规则
/context - 查看会话上下文状态
/summary - 查看交接摘要
/ask <问题> - 单次无历史问答
/new - 开启新会话
/reset - 重置当前会话
/compact - 强制生成交接摘要
/workspace - 查看或设置当前聊天工作目录
/paths - 查看或设置当前聊天可访问目录，可添加多个
/permission - 查看或设置当前聊天权限档位

常用设置：
/workspace set D:/项目目录
/paths add D:/资料目录, E:/共享目录
/permission set admin  # 最大权限
/rules"""

    def _cmd_group_onboarding(self) -> str:
        return """本群还没有配置访问规则。请先由机器人管理员或机器人拥有者设置后再使用。

查看当前规则：
/rules

设置工作目录，并自动放行该目录：
/workspace set D:/项目目录

额外放行多个目录：
/paths add D:/资料目录, E:/共享目录

设置 Claude Code 权限档位：
/permission set admin  # 最大权限

说明：
- workspace 是 Claude Code 的当前工作目录。
- allowed_paths 可以有多个，用 /paths add 或 /paths set 管理。
- 群规则只对当前群生效。"""

    def _cmd_rules(self, effective_rule) -> str:
        allowed_paths = effective_rule.get("allowed_paths") or []
        allowed_text = "\n".join(f"  - {path}" for path in allowed_paths) if allowed_paths else "  - (未设置)"
        permission_profile = effective_rule.get("permission_profile")
        return f"""当前规则：
- session_mode: {effective_rule.get('session_mode')}
- permission_profile: {self._permission_label(permission_profile)}
- workspace: {effective_rule.get('workspace') or '(未设置)'}
- allowed_paths:
{allowed_text}
- custom_prompt: {'(已设置)' if effective_rule.get('custom_prompt') else '(未设置)'}"""

    def _cmd_context(self, session_key: str | None) -> str:
        if not session_key:
            return "当前为无状态模式，无上下文。"
        meta = self.session_store.get(session_key)
        return f"""会话上下文：
- session_key: {session_key}
- message_count: {meta.message_count}
- status: {meta.status}
- summary: {'(有)' if meta.summary else '(无)'}"""

    def _cmd_summary(self, session_key: str | None) -> str:
        if not session_key:
            return "当前无会话摘要。"
        meta = self.session_store.get(session_key)
        if not meta.summary:
            return "当前没有保存的交接摘要。"
        return f"交接摘要：\n{meta.summary[:500]}..."

    def _cmd_ask(self, chat_id, sender, sender_name, content, chat_rule):
        temporary = {"session_mode": "stateless"}
        effective_rule = resolve_rule(chat_rule, sender_id=sender, temporary=temporary)
        prompt = self._build_prompt(chat_id, sender_name, content, effective_rule)
        effective_workspace = effective_rule.get("workspace") or self.config.claude_work_dir
        permission_mode = permission_mode_for_profile(
            effective_rule.get("permission_profile", ""),
            fallback=self.config.claude_permission_mode,
        )
        reply, _ = self._call_claude(prompt, None, cwd=effective_workspace, permission_mode=permission_mode)
        return reply

    def _maybe_rollover_session(self, session_key: str | None, effective_rule, force: bool = False) -> str:
        if not session_key:
            return ""
        meta = self.session_store.get(session_key)
        policy = effective_rule.get("context_policy", {})
        from .session_store import calculate_rollover_score, is_rollover_cooled_down
        score = calculate_rollover_score(meta, policy, force=force)
        threshold = policy.get("score_threshold", 100)
        if score < threshold:
            return ""
        if not force and not is_rollover_cooled_down(meta, policy):
            return ""

        old_session_id = meta.session_id
        summary_prompt = f"""请为下一段 Claude Code 会话生成交接摘要。

当前会话已经进行了 {meta.message_count} 轮对话，输入 {meta.input_chars} 字符，输出 {meta.output_chars} 字符。

请总结：
1. 用户的主要需求和目标
2. 已完成的工作和关键决策
3. 正在进行中的任务和状态
4. 需要在新会话中继续的关键上下文
5. 任何需要注意的约束或配置

摘要应该简洁但信息丰富，帮助新会话快速恢复上下文。"""
        effective_workspace = effective_rule.get("workspace") or self.config.claude_work_dir
        summary, _ = self._call_claude(summary_prompt, old_session_id, cwd=effective_workspace)

        self.session_store.archive_and_rollover(session_key, summary, old_session_id)
        return f"\n\n以下是上一段 Claude Code session 的交接摘要...\n<session_summary>\n{summary}\n</session_summary>"

    def _is_mentioned(
        self,
        content: str,
        bot_name: str,
        mentions: list[dict[str, Any]] | None,
    ) -> bool:
        """Check if the bot is mentioned in the message."""
        # Check @mentions list
        if mentions:
            for mention in mentions:
                mention_ids = mention.get("id", {}) or {}
                if self.config.feishu_app_id in (
                    mention_ids.get("user_id"),
                    mention_ids.get("open_id"),
                    mention_ids.get("union_id"),
                ):
                    return True
                mention_name = mention.get("name", "")
                if mention_name and bot_name and mention_name.lower() == bot_name.lower():
                    return True

        # Check text content for @bot_name
        if bot_name and re.search(
            rf"@{re.escape(bot_name)}", content, re.IGNORECASE
        ):
            return True

        # Check for generic @bot or @机器人
        if re.search(r"@(?:bot|机器人|claude| Claude)", content, re.IGNORECASE):
            return True

        return False

    def _security_for_rule(self, effective_rule: EffectiveRule) -> SecurityPolicy:
        workspace = effective_rule.get("workspace") or self.config.claude_work_dir
        allowed_paths = self._allowed_paths_for_rule(effective_rule)
        return SecurityPolicy(
            permission_mode=self.config.claude_permission_mode,
            allowed_paths=allowed_paths,
            blocked_keywords=self.config.security_blocked_keywords,
            work_dir=workspace,
            data_dir=self.config.bridge_data_dir,
        )

    def _allowed_paths_for_rule(self, effective_rule: EffectiveRule) -> list[str]:
        allowed_paths = list(self.config.security_allowed_paths)
        allowed_paths.extend(effective_rule.get("allowed_paths", []) or [])
        return [str(path) for path in allowed_paths if str(path).strip()]

    def _security_boundary_prompt(self, effective_rule: EffectiveRule) -> str:
        workspace = effective_rule.get("workspace") or self.config.claude_work_dir or "(unset)"
        allowed_paths = self._allowed_paths_for_rule(effective_rule)
        allowed_lines = "\n".join(f"- {path}" for path in allowed_paths) if allowed_paths else "- (none)"
        permission_profile = effective_rule.get("permission_profile", "")
        permission_mode = permission_mode_for_profile(
            permission_profile,
            fallback=self.config.claude_permission_mode,
        )
        return f"""<bridge_security_boundary>
Current chat workspace:
- {workspace}

User-authorized allowed_paths for this chat:
{allowed_lines}

Current chat permission:
- permission_profile: {permission_profile}
- claude_permission_mode: {permission_mode}

Rules:
- Treat the current chat workspace, user-authorized allowed_paths, and bridge-supplied verified file paths as the only local paths the user has authorized for this conversation.
- Do not read, list, open, summarize, or modify files outside those paths, even if the local Claude CLI permission mode would technically allow it.
- Do not claim or imply access to other local directories, other chat workspaces, runtime data, secrets, credentials, logs, or configuration files.
- If asked what files or directories you can access, answer only with the current chat workspace and user-authorized allowed_paths shown above.
</bridge_security_boundary>"""

    def _build_prompt(
        self,
        chat_id: str,
        sender_name: str,
        content: str,
        effective_rule: EffectiveRule,
    ) -> str:
        """Build the prompt sent to Claude CLI."""
        custom_prompt = effective_rule.get("custom_prompt", "")
        workspace = effective_rule.get("workspace", "")

        parts: list[str] = []

        parts.append(self._security_boundary_prompt(effective_rule))

        if custom_prompt:
            parts.append(f"系统提示: {custom_prompt}")

        if workspace:
            parts.append(f"工作目录: {workspace}")

        parts.append(f"用户: {sender_name}")
        parts.append(f"消息: {content}")


        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Claude CLI
    # ------------------------------------------------------------------

    def _find_claude_cli(self) -> str:
        """Find the Claude CLI executable path."""
        cmd = self.config.claude_command
        if os.path.isabs(cmd) or Path(cmd).exists():
            return cmd

        # Search in PATH
        exts = ("", ".exe", ".cmd", ".bat")
        if sys.platform == "win32":
            exts = (".cmd", ".bat", ".exe", "")
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            for ext in exts:
                candidate = Path(path_dir) / (cmd + ext)
                if candidate.exists():
                    return str(candidate)

        # Try npx
        try:
            result = subprocess.run(
                ["npx", "which", "claude"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        return cmd  # fallback, let subprocess fail with clear error

    def _build_claude_args(
        self,
        session_id: str | None,
        *,
        permission_mode: str | None = None,
    ) -> list[str]:
        cli = self._find_claude_cli()
        args = [
            cli,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]

        mode = permission_mode or self.config.claude_permission_mode
        if mode:
            args.extend(["--permission-mode", mode])

        if session_id:
            args.extend(["--resume", session_id])

        return args

    def _is_missing_claude_session_reply(self, reply: str) -> bool:
        text = reply.lower()
        return (
            "no conversation found with session id" in text
            or "claude session 不存在" in text
            or "session 不存在" in text
        )

    def _build_claude_popen_args(self, args: list[str]) -> tuple[list[str] | str, bool]:
        import subprocess
        cli = args[0]
        use_shell = sys.platform == "win32" and Path(cli).suffix.lower() in (".cmd", ".bat")
        if use_shell:
            return subprocess.list2cmdline(args), True
        return args, False

    def _call_claude(
        self,
        prompt: str,
        session_id: str | None,
        *,
        cwd: str | None = None,
        permission_mode: str | None = None,
    ) -> tuple[str, str | None]:
        """Call Claude CLI and parse stream-json output."""
        args = self._build_claude_args(
            session_id,
            permission_mode=permission_mode,
        )

        env = os.environ.copy()
        env["CLYDE_NO_ANIMATION"] = "1"

        self.bridge_logger.debug(f"Claude cmd: {' '.join(args[:6])}...")

        try:
            popen_args, use_shell = self._build_claude_popen_args(args)
            proc = subprocess.Popen(
                popen_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                cwd=cwd or self.config.claude_work_dir or None,
                shell=use_shell,
            )
            stdout, stderr = proc.communicate(
                input=prompt + "\n", timeout=600
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            self.bridge_logger.error("Claude CLI调用超时")
            return "[错误: Claude CLI调用超时]", None
        except Exception as e:
            self.bridge_logger.exception(f"无法调用Claude CLI: {e}")
            return f"[错误: 无法调用Claude CLI: {e}]", None

        if stderr:
            self.bridge_logger.warning(f"Claude stderr: {stderr[:500]}")
            if "No conversation found with session ID" in stderr:
                return f"[错误: {stderr.strip()}]", None

        final_text = ""
        new_session_id: str | None = None

        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            if event_type == "system":
                new_session_id = event.get(
                    "session_id", new_session_id
                )
            elif event_type == "stream_event":
                sub = event.get("event", {})
                sub_type = sub.get("type", "")
                if sub_type == "content_block_delta":
                    delta = sub.get("delta", {})
                    if delta.get("type") == "text_delta":
                        final_text += delta.get("text", "")
            elif event_type == "result":
                result = event.get("result", "")
                if result and not final_text:
                    final_text = result

        return final_text or "[Claude未返回内容]", new_session_id or session_id

    # ------------------------------------------------------------------
    # Feishu API
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Get Feishu tenant_access_token with caching."""
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        url = (
            f"{self.config.feishu_domain}"
            f"/open-apis/auth/v3/tenant_access_token/internal"
        )
        resp = requests.post(
            url,
            json={
                "app_id": self.config.feishu_app_id,
                "app_secret": self.config.feishu_app_secret,
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Token failed: {data}")

        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        self.bridge_logger.info("Feishu token refreshed")
        return self._token

    def _prepare_message_content(self, content: str, msg_type: str) -> str:
        if msg_type != "text":
            return content
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "text" in data:
                return content
        except json.JSONDecodeError:
            pass
        return json.dumps({"text": content}, ensure_ascii=False, separators=(",", ":"))

    def _add_message_reaction(self, message_id: str) -> str | None:
        """Add a temporary Feishu reaction to the source message."""
        try:
            url = f"{self.config.feishu_domain}/open-apis/im/v1/messages/{message_id}/reactions"
            headers = {
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
            }
            payload = {
                "reaction_type": {
                    "emoji_type": _PROCESSING_REACTION_EMOJI,
                }
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                self.bridge_logger.warning(f"Add message reaction failed: {result}")
                return None
            reaction_id = result.get("data", {}).get("reaction_id")
            if reaction_id:
                self.bridge_logger.info(f"Added message reaction: {message_id}/{reaction_id}")
            return reaction_id
        except Exception as e:
            self.bridge_logger.warning(f"Add message reaction error: {e}")
            return None

    def _delete_message_reaction(self, message_id: str, reaction_id: str) -> bool:
        """Delete a Feishu reaction previously added by this bot."""
        try:
            url = (
                f"{self.config.feishu_domain}"
                f"/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}"
            )
            headers = {
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
            }
            resp = requests.delete(url, headers=headers, timeout=30)
            result = resp.json()
            if result.get("code") != 0:
                self.bridge_logger.warning(f"Delete message reaction failed: {result}")
                return False
            self.bridge_logger.info(f"Deleted message reaction: {message_id}/{reaction_id}")
            return True
        except Exception as e:
            self.bridge_logger.warning(f"Delete message reaction error: {e}")
            return False

    def _send_reply(
        self,
        chat_id: str,
        content: str,
        msg_type: str = "text",
        reply_to_message_id: str = "",
    ) -> bool:
        """Send a reply message via Feishu API."""
        if reply_to_message_id:
            url = (
                f"{self.config.feishu_domain}/open-apis/im/v1/messages/"
                f"{reply_to_message_id}/reply"
            )
            params = None
        else:
            url = f"{self.config.feishu_domain}/open-apis/im/v1/messages"
            params = {"receive_id_type": "chat_id"}
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }
        payload = {
            "msg_type": msg_type,
            "content": self._prepare_message_content(content, msg_type),
        }
        if reply_to_message_id:
            payload["reply_in_thread"] = False
        else:
            payload["receive_id"] = chat_id

        try:
            kwargs: dict[str, Any] = {
                "url": url,
                "headers": headers,
                "json": payload,
                "timeout": 30,
            }
            if params is not None:
                kwargs["params"] = params
            resp = requests.post(
                **kwargs,
            )
            result = resp.json()
            if result.get("code") != 0:
                self.bridge_logger.error(
                    f"Send reply failed: {result}"
                )
                return False
            return True
        except Exception as e:
            self.bridge_logger.exception(f"Send reply error: {e}")
            return False

    def _file_upload_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        mapping = {
            ".doc": "doc",
            ".docx": "docx",
            ".xls": "xls",
            ".xlsx": "xlsx",
            ".ppt": "ppt",
            ".pptx": "pptx",
            ".pdf": "pdf",
        }
        return mapping.get(suffix, "stream")

    def _upload_file(self, path: str | Path) -> str | None:
        """Upload a local file to Feishu and return file_key."""
        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_file():
            self.bridge_logger.warning(f"Upload file missing: {target}")
            return None

        max_bytes = int(self.config.bridge_max_upload_mb) * 1024 * 1024
        file_size = target.stat().st_size
        if file_size <= 0:
            self.bridge_logger.warning(f"Upload file is empty: {target}")
            return None
        if max_bytes > 0 and file_size > max_bytes:
            self.bridge_logger.warning(
                f"Upload file too large: {target} ({file_size} bytes)"
            )
            return None

        url = f"{self.config.feishu_domain}/open-apis/im/v1/files"
        headers = {"Authorization": f"Bearer {self._get_token()}"}
        mime_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = {
            "file_type": self._file_upload_type(target),
            "file_name": target.name,
        }

        try:
            with target.open("rb") as f:
                files = {"file": (target.name, f, mime_type)}
                resp = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=120,
                )
            result = resp.json()
            if result.get("code") != 0:
                self.bridge_logger.error(f"Upload file failed: {result}")
                return None
            file_key = result.get("data", {}).get("file_key")
            if not file_key:
                self.bridge_logger.error(f"Upload file missing file_key: {result}")
                return None
            self.bridge_logger.info(f"File uploaded: {target} -> {file_key}")
            return str(file_key)
        except Exception as e:
            self.bridge_logger.exception(f"Upload file error: {e}")
            return None

    def _send_local_file(
        self,
        chat_id: str,
        path: str | Path,
        reply_to_message_id: str = "",
    ) -> bool:
        file_key = self._upload_file(path)
        if not file_key:
            return False
        content = json.dumps({"file_key": file_key}, ensure_ascii=False)
        return self._send_reply(
            chat_id,
            content,
            "file",
            reply_to_message_id=reply_to_message_id,
        )

    def _download_image(
        self, message_id: str, image_key: str
    ) -> str | None:
        """Download an image from Feishu."""
        if not image_key:
            return None

        url = (
            f"{self.config.feishu_domain}"
            f"/open-apis/im/v1/messages/{message_id}"
            f"/resources/{image_key}?type=image"
        )
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=120,
            )
            if resp.status_code == 200:
                self.images_dir.mkdir(parents=True, exist_ok=True)
                save_path = (
                    self.images_dir
                    / f"img_{int(time.time())}_{image_key[:20]}.png"
                )
                save_path.write_bytes(resp.content)
                return str(save_path)
            else:
                self.bridge_logger.warning(
                    f"Download image failed: HTTP {resp.status_code}"
                )
        except Exception as e:
            self.bridge_logger.exception(f"Download image error: {e}")
        return None

    def _process_audio(
        self, message_id: str, content_obj: dict[str, Any]
    ) -> str | None:
        """Download and transcribe an audio message."""
        audio_key = content_obj.get("file_key", "")
        if not audio_key:
            return None

        # Download audio file
        url = (
            f"{self.config.feishu_domain}"
            f"/open-apis/im/v1/messages/{message_id}"
            f"/resources/{audio_key}?type=file"
        )
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=120,
            )
            if resp.status_code != 200:
                self.bridge_logger.warning(
                    f"Download audio failed: HTTP {resp.status_code}"
                )
                return None

            self.attachments_dir.mkdir(parents=True, exist_ok=True)
            audio_path = self.attachments_dir / f"audio_{message_id[:20]}.amr"
            audio_path.write_bytes(resp.content)
            self.bridge_logger.info(f"Audio saved: {audio_path}")

        except Exception as e:
            self.bridge_logger.exception(f"Download audio error: {e}")
            return None

        # Auto-add ffmpeg to PATH
        try:
            import imageio_ffmpeg

            ffmpeg_bin = str(Path(imageio_ffmpeg.__file__).parent / "binaries")
            if ffmpeg_bin not in os.environ.get("PATH", ""):
                os.environ["PATH"] = (
                    ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
                )
                self.bridge_logger.info(f"Added ffmpeg to PATH: {ffmpeg_bin}")
        except ImportError:
            pass

        # Transcribe with faster-whisper
        try:
            from faster_whisper import WhisperModel

            self.bridge_logger.info(
                f"Loading Whisper model '{self.config.whisper_model}'..."
            )
            model = WhisperModel(
                self.config.whisper_model,
                device="cpu",
                compute_type="int8",
            )
            self.bridge_logger.info(
                f"Whisper model '{self.config.whisper_model}' loaded"
            )
            segments, _ = model.transcribe(str(audio_path))
            text = " ".join(s.text for s in segments)
            self.bridge_logger.info(f"Transcribed: {text[:100]}...")
            return text
        except ImportError:
            return "[语音转文字不可用: 未安装 faster-whisper]"
        except Exception as e:
            self.bridge_logger.exception(f"语音转录失败: {e}")
            return f"[语音转录失败: {e}]"

    def _process_file(
        self, message_id: str, content_obj: dict[str, Any]
    ) -> str | None:
        """Download a file attachment."""
        file_key = content_obj.get("file_key", "")
        file_name = content_obj.get("file_name", "unknown")
        if not file_key:
            return None

        url = (
            f"{self.config.feishu_domain}"
            f"/open-apis/im/v1/messages/{message_id}"
            f"/resources/{file_key}?type=file"
        )
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=120,
            )
            if resp.status_code == 200:
                self.attachments_dir.mkdir(parents=True, exist_ok=True)
                safe_name = re.sub(r"[^\w.\-]", "_", file_name)
                save_path = self.attachments_dir / f"file_{int(time.time())}_{safe_name}"
                save_path.write_bytes(resp.content)
                self.bridge_logger.info(f"File saved: {save_path}")
                return str(save_path)
            else:
                self.bridge_logger.warning(
                    f"Download file failed: HTTP {resp.status_code}"
                )
        except Exception as e:
            self.bridge_logger.exception(f"Download file error: {e}")
        return None

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _save_sessions(self) -> None:
        """Persist session metadata through SessionStore only."""
        try:
            self.session_store.save()
            self.bridge_logger.info(
                f"Saved {len(self.session_store._data)} sessions"
            )
        except Exception as e:
            self.bridge_logger.warning(f"Failed to save sessions: {e}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Feishu-Claude Code Bridge"
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.toml",
        help="Path to config.toml (default: config.toml)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show bridge status",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop running bridge",
    )
    parser.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        help="Run in foreground (default)",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run self-check",
    )
    args = parser.parse_args()

    # Load config early for PID path
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = _WORK_DIR / config_path

    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"Failed to load config: {e}")
        sys.exit(1)

    pid_file = Path(config.bridge_data_dir).resolve() / "bridge.pid"

    if args.doctor:
        from .doctor import run_doctor, print_results
        results = run_doctor(args.config)
        sys.exit(print_results(results))

    if args.status:
        _show_status(pid_file)
        return

    if args.stop:
        _stop_bridge(pid_file)
        return

    # Check if already running
    if _is_running(pid_file):
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        print(f"Bridge is already running (PID {pid}). Use --stop to stop it.")
        sys.exit(1)

    # Validate required config
    if not config.feishu_app_id or not config.feishu_app_secret:
        print(
            "Error: feishu_app_id and feishu_app_secret are required. "
            "Please set them in config.toml or environment variables."
        )
        sys.exit(1)

    # Write PID and run
    _write_pid(pid_file)
    bridge = Bridge(config, config_path=config_path)
    bridge.run()


if __name__ == "__main__":
    main()
