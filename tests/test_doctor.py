from feishu_claudecode_qiao.doctor import run_doctor, print_results


def test_doctor_runs_without_crash(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        f"""
[bridge]
data_dir = "{tmp_path.as_posix()}"
""".strip(),
        encoding="utf-8",
    )

    results = run_doctor(str(config))
    assert isinstance(results, list)
    assert len(results) > 0
    checks = {r["check"] for r in results}
    assert "config.toml" in checks


def test_doctor_levels_present():
    results = run_doctor("__missing_test_config__.toml")
    for r in results:
        assert "level" in r
        assert r["level"] in {"required", "optional", "warning"}


def test_doctor_reports_sessions_memory_gateway_and_websocket(tmp_path):
    import json

    config = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config.write_text(
        f"""
[bridge]
data_dir = "{data_dir.as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    (data_dir / "sessions.json").write_text(
        json.dumps(
            {
                "chat:c1": {
                    "session_id": "sid_1",
                    "memory": {"rolling_summary": "remember me"},
                    "memory_history": [{"summary": "old"}],
                },
                "chat:c2": {"session_id": ""},
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "feishu_ws.pid").write_text("999999", encoding="utf-8")

    results = {item["check"]: item for item in run_doctor(str(config))}

    assert results["sessions_file"]["ok"] is True
    assert "2 sessions" in results["sessions_file"]["hint"]
    assert results["chat_memory"]["ok"] is True
    assert "1 with memory" in results["chat_memory"]["hint"]
    assert results["feishu_gateway"]["ok"] is True
    assert results["websocket_pid"]["ok"] is False
    assert results["websocket_pid"]["level"] == "warning"


def test_doctor_requires_websocket_metadata_to_match_config(tmp_path, monkeypatch):
    import json
    import os

    config = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config.write_text(
        f"""
[bridge]
data_dir = "{data_dir.as_posix()}"
ws_profile = "qiao-test"
""".strip(),
        encoding="utf-8",
    )
    (data_dir / "feishu_ws.pid").write_text(str(os.getpid()), encoding="utf-8")
    (data_dir / "feishu_ws.meta.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "profile": "other-profile",
                "config_path": str(config.resolve()),
                "data_dir": str(data_dir.resolve()),
            }
        ),
        encoding="utf-8",
    )

    results = {item["check"]: item for item in run_doctor(str(config))}

    assert results["websocket_pid"]["ok"] is False
    assert "metadata" in results["websocket_pid"]["hint"].lower()


def test_doctor_reports_explicit_feishu_backends(tmp_path):
    config = tmp_path / "config.toml"
    data_dir = tmp_path / "data"
    config.write_text(
        f"""
[feishu]
gateway_backend = "lark_oapi"
event_backend = "lark_oapi_ws"

[bridge]
data_dir = "{data_dir.as_posix()}"
""".strip(),
        encoding="utf-8",
    )

    results = {item["check"]: item for item in run_doctor(str(config))}

    assert results["feishu_gateway_backend"]["ok"] is False
    assert "lark_oapi" in results["feishu_gateway_backend"]["hint"]
    assert results["feishu_event_backend"]["ok"] is False
    assert "lark_oapi_ws" in results["feishu_event_backend"]["hint"]


def test_print_results_optional_failure_does_not_return_one():
    results = [
        {"check": "whisper", "ok": False, "level": "optional"},
        {"check": "claude_cli", "ok": True, "level": "required"},
    ]
    assert print_results(results) == 0


def test_print_results_required_failure_returns_one():
    results = [
        {"check": "feishu_app_id", "ok": False, "level": "required"},
    ]
    assert print_results(results) == 1
