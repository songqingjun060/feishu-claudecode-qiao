from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def make_bridge(tmp_path):
    return Bridge(Config(
        feishu_app_id="cli_test",
        feishu_app_secret="secret",
        bridge_data_dir=str(tmp_path),
    ))


def test_build_claude_popen_args_for_normal_exe(tmp_path):
    bridge = make_bridge(tmp_path)
    popen_args, shell = bridge._build_claude_popen_args(["claude", "--print"])
    assert popen_args == ["claude", "--print"]
    assert shell is False


def test_build_claude_popen_args_for_cmd_uses_list2cmdline(tmp_path):
    import subprocess
    bridge = make_bridge(tmp_path)
    popen_args, shell = bridge._build_claude_popen_args([r"C:\Program Files\Claude\claude.cmd", "--print"])
    assert isinstance(popen_args, str)
    assert '"C:\\Program Files\\Claude\\claude.cmd"' in popen_args
    assert shell is True


def test_build_claude_args_includes_bypass_permission_mode(tmp_path):
    bridge = make_bridge(tmp_path)
    args = bridge._build_claude_args(
        session_id=None,
        permission_mode="bypassPermissions",
    )

    assert "--permission-mode" in args
    idx = args.index("--permission-mode")
    assert args[idx + 1] == "bypassPermissions"


def test_build_claude_args_includes_default_permission_mode(tmp_path):
    bridge = make_bridge(tmp_path)
    args = bridge._build_claude_args(
        session_id="sid_1",
        permission_mode="default",
    )

    assert "--permission-mode" in args
    idx = args.index("--permission-mode")
    assert args[idx + 1] == "default"
    assert "--resume" in args
    resume_idx = args.index("--resume")
    assert args[resume_idx + 1] == "sid_1"


def test_find_claude_cli_prefers_executable_extension(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("not executable on windows", encoding="utf-8")
    cmd_path = bin_dir / "claude.cmd"
    cmd_path.write_text("@echo off\n", encoding="utf-8")

    bridge = make_bridge(tmp_path)
    monkeypatch.setenv("PATH", str(bin_dir))

    assert bridge._find_claude_cli().lower().endswith("claude.cmd")
