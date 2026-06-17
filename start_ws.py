#!/usr/bin/env python3
"""Manage the lark-cli event subscriber used by this bridge.

Usage:
    python start_ws.py start --config config.realtest.toml --profile qiao-test
    python start_ws.py stop --config config.realtest.toml
    python start_ws.py status --config config.realtest.toml
    python start_ws.py restart --config config.realtest.toml --profile qiao-test
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from feishu_claudecode_qiao.config import load_config
except Exception:
    load_config = None  # type: ignore[assignment]


EVENT_TYPES = "im.message.receive_v1,im.message.recalled_v1"


def _config_data_dir(config_path: str | Path) -> Path:
    if load_config is None:
        return Path("data")
    return Path(load_config(config_path).bridge_data_dir).resolve()


def _resolved_config_path(config_path: str | Path) -> Path:
    return Path(config_path).expanduser().resolve()


def _paths(config_path: str | Path) -> tuple[Path, Path, Path, Path]:
    data_dir = _config_data_dir(config_path)
    return (
        data_dir / "feishu_ws.pid",
        data_dir / "feishu_ws.meta.json",
        data_dir / "logs" / "feishu_ws_events.jsonl",
        data_dir / "logs" / "feishu_ws.log",
    )


def _lark_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HTTPS_PROXY": "",
            "https_proxy": "",
            "HTTP_PROXY": "",
            "http_proxy": "",
            "LARK_CLI_NO_PROXY": "1",
        }
    )
    return env


def _find_lark_cli() -> str:
    for name in ("lark-cli", "lark-cli.cmd", "lark-cli.CMD"):
        path = shutil.which(name)
        if path:
            return path
    fallback = Path(r"D:\OpenClaw\npm-global\lark-cli.CMD")
    return str(fallback) if fallback.exists() else "lark-cli"


def _pid_running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_profile_subscribers(profile: str) -> None:
    if sys.platform != "win32":
        return
    ps = (
        "$profileName = " + json.dumps(profile) + "\n"
        "$current = $PID\n"
        "$matches = Get-CimInstance Win32_Process | Where-Object { "
        "$_.ProcessId -ne $current -and "
        "$_.CommandLine -like ('*--profile*' + $profileName + '*') -and "
        "$_.CommandLine -like '*event*+subscribe*' "
        "} | Select-Object -ExpandProperty ProcessId\n"
        "$matches | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }\n"
        "$matches | ForEach-Object { Write-Output $_ }\n"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
    )
    killed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if killed:
        print(f"[OK] Stopped stale {profile} subscribers: {', '.join(killed)}")


def _expected_meta(config_path: str | Path, profile: str) -> dict[str, str]:
    data_dir = _config_data_dir(config_path)
    return {
        "profile": profile,
        "config_path": str(_resolved_config_path(config_path)),
        "data_dir": str(data_dir),
    }


def _meta_matches(config_path: str | Path, profile: str, pid: int) -> bool:
    _, meta_file, _, _ = _paths(config_path)
    if not meta_file.exists():
        return False
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = _expected_meta(config_path, profile)
    return (
        int(meta.get("pid", 0)) == pid
        and meta.get("profile") == expected["profile"]
        and str(Path(meta.get("config_path", "")).resolve()) == expected["config_path"]
        and str(Path(meta.get("data_dir", "")).resolve()) == expected["data_dir"]
    )


def _write_meta(config_path: str | Path, profile: str, pid: int) -> None:
    _, meta_file, _, _ = _paths(config_path)
    meta_file.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        **_expected_meta(config_path, profile),
        "pid": pid,
        "started_at": time.time(),
    }
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def is_running(config_path: str | Path, profile: str | None = None) -> bool:
    pid_file, _, _, _ = _paths(config_path)
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if not _pid_running(pid):
        return False
    if profile is None:
        return True
    return _meta_matches(config_path, profile, pid)


def stop(config_path: str | Path, profile: str | None = None) -> int:
    pid_file, meta_file, _, _ = _paths(config_path)
    if not pid_file.exists():
        print("[INFO] WebSocket subscriber is not running")
        meta_file.unlink(missing_ok=True)
        return 0

    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        meta_file.unlink(missing_ok=True)
        print("[WARN] Removed invalid PID file")
        return 0

    if profile is not None and _pid_running(pid) and not _meta_matches(config_path, profile, pid):
        print(f"[WARN] PID {pid} metadata does not match profile={profile}; not stopping it")
        return 1

    if _pid_running(pid):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, 9)
        print(f"[OK] Stopped WebSocket subscriber PID={pid}")
    else:
        print(f"[INFO] PID {pid} is not running")
    pid_file.unlink(missing_ok=True)
    meta_file.unlink(missing_ok=True)
    return 0


def start(config_path: str | Path, profile: str, force: bool) -> int:
    pid_file, _, output_file, log_file = _paths(config_path)
    if force:
        _kill_profile_subscribers(profile)
        time.sleep(1)
    if is_running(config_path, profile=profile):
        print("[WARN] Existing WebSocket subscriber found; stopping it first")
        stop(config_path, profile=profile)
        time.sleep(1)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    lark = _find_lark_cli()
    args = [
        lark,
        "--profile",
        profile,
        "event",
        "+subscribe",
        "--as",
        "bot",
        "--event-types",
        EVENT_TYPES,
        "--compact",
    ]
    if force:
        args.append("--force")

    out_f = output_file.open("a", encoding="utf-8")
    log_f = log_file.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        args,
        cwd=Path(__file__).parent,
        stdout=out_f,
        stderr=log_f,
        env=_lark_env(),
    )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    _write_meta(config_path, profile, proc.pid)
    print(f"[OK] WebSocket subscriber started PID={proc.pid}")
    print(f"[INFO] Profile: {profile}")
    print(f"[INFO] Output: {output_file}")
    print(f"[INFO] Log: {log_file}")
    return 0


def status(config_path: str | Path, profile: str | None = None) -> int:
    pid_file, meta_file, output_file, log_file = _paths(config_path)
    running = is_running(config_path, profile=profile)
    print("[OK] WebSocket subscriber is running" if running else "[STOPPED] WebSocket subscriber is not running")
    if pid_file.exists():
        print(f"PID file: {pid_file} ({pid_file.read_text(encoding='utf-8').strip()})")
    if meta_file.exists():
        print(f"Meta file: {meta_file}")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            print(f"Profile: {meta.get('profile')}")
            print(f"Config: {meta.get('config_path')}")
        except json.JSONDecodeError:
            print("[WARN] WebSocket metadata is invalid JSON")
    for path in (output_file, log_file):
        if path.exists():
            print(f"{path}: {path.stat().st_size} bytes, updated {time.ctime(path.stat().st_mtime)}")
    if output_file.exists():
        lines = [line for line in output_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        for line in lines[-3:]:
            try:
                event = json.loads(line)
                print(f"event: {event.get('type') or event.get('header', {}).get('event_type') or 'unknown'}")
            except json.JSONDecodeError:
                print(f"event: {line[:80]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage lark-cli event subscriber")
    parser.add_argument("action", choices=["start", "stop", "status", "restart"])
    parser.add_argument("--config", default="config.toml", help="Bridge TOML config path")
    parser.add_argument("--profile", default="qiao-test", help="lark-cli profile for this Feishu app")
    parser.add_argument("--force", action="store_true", help="Pass --force to lark-cli")
    args = parser.parse_args()

    if args.action == "start":
        return start(args.config, args.profile, args.force)
    if args.action == "stop":
        return stop(args.config, args.profile)
    if args.action == "restart":
        stop(args.config, args.profile)
        time.sleep(1)
        return start(args.config, args.profile, args.force)
    return status(args.config, args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
