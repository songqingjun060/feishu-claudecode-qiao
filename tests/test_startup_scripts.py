from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_single_user_startup_script_is_run_foreground():
    assert (ROOT / "run_foreground.ps1").exists()
    assert not (ROOT / "start_all.ps1").exists()


def test_one_click_cmd_starts_foreground_restart():
    script = ROOT / "start_qiao.cmd"
    assert script.exists()

    text = script.read_text(encoding="utf-8").lower()
    assert "run_foreground.ps1" in text
    assert "-restart" in text
    assert "-noexit" in text
    assert "-background" not in text
    assert "%~dp0" in text


def test_one_click_cmd_has_safe_help_mode():
    text = (ROOT / "start_qiao.cmd").read_text(encoding="utf-8").lower()

    assert "%~1" in text
    assert "/?" in text
    assert "--help" in text
    assert "usage:" in text


def test_docs_do_not_reference_removed_start_all_script():
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "DEPLOYMENT.md",
        ROOT / "docs" / "TROUBLESHOOTING.md",
    ]

    for path in docs:
        if path.exists():
            assert "start_all.ps1" not in path.read_text(encoding="utf-8")
