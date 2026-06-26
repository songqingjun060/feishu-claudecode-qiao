from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_single_user_startup_script_is_run_foreground():
    assert (ROOT / "run_foreground.ps1").exists()
    assert not (ROOT / "start_all.ps1").exists()


def test_docs_do_not_reference_removed_start_all_script():
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "DEPLOYMENT.md",
        ROOT / "docs" / "TROUBLESHOOTING.md",
    ]

    for path in docs:
        if path.exists():
            assert "start_all.ps1" not in path.read_text(encoding="utf-8")
