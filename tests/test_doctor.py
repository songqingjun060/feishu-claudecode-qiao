from feishu_claudecode_qiao.doctor import run_doctor, print_results


def test_doctor_runs_without_crash(tmp_path):
    results = run_doctor()
    assert isinstance(results, list)
    assert len(results) > 0
    checks = {r["check"] for r in results}
    assert "config.toml" in checks


def test_doctor_levels_present():
    results = run_doctor()
    for r in results:
        assert "level" in r
        assert r["level"] in {"required", "optional", "warning"}


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
