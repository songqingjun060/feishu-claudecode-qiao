from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import load_config


REQUIRED_CHECKS = {"feishu_app_id", "feishu_app_secret", "claude_cli", "data_dir_writable"}
OPTIONAL_CHECKS = {"whisper"}


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _load_sessions(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def run_doctor(config_path: str = "config.toml") -> list[dict[str, Any]]:
    results = []
    cfg = load_config(config_path)

    # config.toml
    results.append({"check": "config.toml", "ok": Path(config_path).exists(), "level": "warning"})

    # feishu credentials
    results.append({"check": "feishu_app_id", "ok": bool(cfg.feishu_app_id), "level": "required", "hint": "已配置" if cfg.feishu_app_id else "未配置"})
    results.append({"check": "feishu_app_secret", "ok": bool(cfg.feishu_app_secret), "level": "required", "hint": "已配置" if cfg.feishu_app_secret else "未配置"})

    # claude cli
    claude_found = bool(shutil.which(cfg.claude_command))
    results.append({"check": "claude_cli", "ok": claude_found, "level": "required", "hint": shutil.which(cfg.claude_command) or "未找到"})

    # data_dir writable
    data_dir = Path(cfg.bridge_data_dir).resolve()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".doctor_write_test"
        test_file.write_text("ok")
        test_file.unlink()
        results.append({"check": "data_dir_writable", "ok": True, "level": "required"})
    except Exception as e:
        results.append({"check": "data_dir_writable", "ok": False, "level": "required", "hint": str(e)})

    sessions_file = data_dir / "sessions.json"
    sessions = _load_sessions(sessions_file) if sessions_file.exists() else {}
    active_sessions = sum(1 for item in sessions.values() if isinstance(item, dict) and item.get("session_id"))
    memory_sessions = sum(
        1
        for item in sessions.values()
        if isinstance(item, dict)
        and ((item.get("memory") or {}).get("rolling_summary") or item.get("memory_history"))
    )
    results.append(
        {
            "check": "sessions_file",
            "ok": sessions_file.exists(),
            "level": "warning",
            "hint": f"{len(sessions)} sessions, {active_sessions} active Claude sessions",
        }
    )
    results.append(
        {
            "check": "chat_memory",
            "ok": memory_sessions > 0,
            "level": "warning",
            "hint": f"{memory_sessions} with memory",
        }
    )

    ws_pid_file = data_dir / "feishu_ws.pid"
    ws_meta_file = data_dir / "feishu_ws.meta.json"
    ws_ok = False
    ws_hint = "??? PID ??"
    if ws_pid_file.exists():
        try:
            pid = int(ws_pid_file.read_text(encoding="utf-8").strip())
            pid_ok = _pid_running(pid)
            meta_ok = False
            if ws_meta_file.exists():
                try:
                    meta = json.loads(ws_meta_file.read_text(encoding="utf-8"))
                    meta_ok = (
                        int(meta.get("pid", 0)) == pid
                        and meta.get("profile") == cfg.bridge_ws_profile
                        and str(Path(str(meta.get("config_path", ""))).resolve()) == str(Path(config_path).resolve())
                        and str(Path(str(meta.get("data_dir", ""))).resolve()) == str(data_dir)
                    )
                except Exception:
                    meta_ok = False
            ws_ok = pid_ok and meta_ok
            if pid_ok and not meta_ok:
                ws_hint = f"PID {pid} running but metadata does not match config/profile"
            else:
                ws_hint = f"PID {pid} {'???' if ws_ok else '???'}"
        except Exception as e:
            ws_hint = f"PID ????: {e}"
    results.append({"check": "websocket_pid", "ok": ws_ok, "level": "warning", "hint": ws_hint})

    gateway_backend = (cfg.feishu_gateway_backend or "current").lower()
    gateway_ok = gateway_backend in {"current", "http", "legacy"}
    results.append(
        {
            "check": "feishu_gateway_backend",
            "ok": gateway_ok,
            "level": "warning",
            "hint": (
                f"{cfg.feishu_gateway_backend} active"
                if gateway_ok
                else f"{cfg.feishu_gateway_backend} selected but not implemented"
            ),
        }
    )

    event_backend = (cfg.feishu_event_backend or "start_ws").lower()
    event_ok = event_backend in {"start_ws", "lark_cli", "lark-cli"}
    results.append(
        {
            "check": "feishu_event_backend",
            "ok": event_ok,
            "level": "warning",
            "hint": (
                f"{cfg.feishu_event_backend} active"
                if event_ok
                else f"{cfg.feishu_event_backend} selected but not implemented"
            ),
        }
    )

    try:
        from .feishu_gateway import CurrentFeishuGateway, FeishuGateway

        gateway_ok = bool(CurrentFeishuGateway and FeishuGateway)
        gateway_hint = "FeishuGateway 可导入"
    except Exception as e:
        gateway_ok = False
        gateway_hint = str(e)
    results.append({"check": "feishu_gateway", "ok": gateway_ok, "level": "optional", "hint": gateway_hint})

    # whisper
    try:
        import faster_whisper
        results.append({"check": "whisper", "ok": True, "level": "optional"})
    except ImportError:
        results.append({"check": "whisper", "ok": False, "level": "optional", "hint": "pip install faster-whisper"})

    return results


def print_results(results: list[dict[str, Any]]) -> int:
    failed_required = False
    for r in results:
        level = r.get("level", "required")
        ok = r["ok"]
        if ok:
            status = "OK"
        elif level == "optional":
            status = "WARN"
        else:
            status = "FAIL"
            failed_required = True
        hint = f" ({r.get('hint', '')})" if r.get("hint") else ""
        print(f"[{status}] {r['check']}{hint}")
    return 1 if failed_required else 0
