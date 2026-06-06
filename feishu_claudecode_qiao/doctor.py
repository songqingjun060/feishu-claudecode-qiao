from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from .config import load_config


REQUIRED_CHECKS = {"feishu_app_id", "feishu_app_secret", "claude_cli", "data_dir_writable"}
OPTIONAL_CHECKS = {"whisper"}


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
