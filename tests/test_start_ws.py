import json
from pathlib import Path

import start_ws


def write_config(config_path: Path, data_dir: Path) -> None:
    config_path.write_text(
        f"""
[bridge]
data_dir = "{data_dir.as_posix()}"
ws_profile = "qiao-test"
""".strip(),
        encoding="utf-8",
    )


def test_start_writes_profile_binding_metadata(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    write_config(config_path, data_dir)

    class FakeProcess:
        pid = 12345

    monkeypatch.setattr(start_ws, "_find_lark_cli", lambda: "lark-cli")
    monkeypatch.setattr(start_ws.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    assert start_ws.start(config_path, "qiao-test", force=False) == 0

    meta = json.loads((data_dir / "feishu_ws.meta.json").read_text(encoding="utf-8"))
    assert meta["pid"] == 12345
    assert meta["profile"] == "qiao-test"
    assert Path(meta["config_path"]) == config_path.resolve()
    assert Path(meta["data_dir"]) == data_dir.resolve()


def test_is_running_requires_matching_profile_metadata(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_config(config_path, data_dir)
    (data_dir / "feishu_ws.pid").write_text("12345", encoding="utf-8")
    (data_dir / "feishu_ws.meta.json").write_text(
        json.dumps(
            {
                "pid": 12345,
                "profile": "other-profile",
                "config_path": str(config_path.resolve()),
                "data_dir": str(data_dir.resolve()),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(start_ws, "_pid_running", lambda pid: True)

    assert start_ws.is_running(config_path, profile="qiao-test") is False
