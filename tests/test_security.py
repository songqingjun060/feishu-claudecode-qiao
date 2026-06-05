from pathlib import Path

import pytest

from feishu_claudecode_qiao.security import SecurityPolicy, extract_path_candidates


@pytest.fixture
def security():
    return SecurityPolicy(
        permission_mode="bypassPermissions",
        allowed_paths=["/tmp/custom"],
        blocked_keywords=["敏感词", "测试屏蔽"],
        work_dir=".",
        data_dir="data",
    )


def test_path_allowed_work_dir(security):
    assert security.is_path_allowed(".") is True
    assert security.is_path_allowed("data") is True


def test_path_allowed_custom(security):
    assert security.is_path_allowed("/tmp/custom") is True
    assert security.is_path_allowed("/tmp/custom/subdir") is True


def test_path_blocked_system(security):
    assert security.is_path_allowed("C:/Windows/system32") is False
    assert security.is_path_allowed("C:/Program Files/app") is False
    assert security.is_path_allowed("/etc/passwd") is False
    assert security.is_path_allowed("/usr/bin") is False
    assert security.is_path_allowed("/root/.bashrc") is False


def test_path_blocked_ssh(security):
    assert security.is_path_allowed("/home/user/.ssh/id_rsa") is False
    assert security.is_path_allowed("/home/user/.aws/credentials") is False
    assert security.is_path_allowed("/home/user/.kube/config") is False
    assert security.is_path_allowed("/home/user/.gnupg") is False


def test_path_blocked_keywords_in_path(security):
    assert security.is_path_allowed("/home/user/passwords.txt") is False
    assert security.is_path_allowed("/data/secrets.env") is False
    assert security.is_path_allowed("/app/token.json") is False


def test_message_no_blocked_keywords(security):
    blocked, warning = security.check_message("这是一条正常的消息")
    assert blocked is False
    assert warning == ""


def test_message_blocked_keywords(security):
    blocked, warning = security.check_message("这条消息包含敏感词")
    assert blocked is True
    assert "敏感词" in warning


def test_message_blocked_multiple_keywords(security):
    blocked, warning = security.check_message("包含测试屏蔽和敏感词")
    assert blocked is True
    assert "敏感词" in warning
    assert "测试屏蔽" in warning


def test_check_risky_intent_delete(security):
    result = security.check_risky_intent("请删除所有文件")
    assert result.risky is True
    assert result.category == "delete"


def test_check_risky_intent_shell(security):
    result = security.check_risky_intent("执行 bash script.sh")
    assert result.risky is True
    assert result.category == "shell"


def test_check_risky_intent_normal(security):
    result = security.check_risky_intent("这是一段正常的对话")
    assert result.risky is False


def test_check_risky_intent_rm_rf(security):
    result = security.check_risky_intent("rm -rf /")
    assert result.risky is True
    assert result.category == "delete"


def test_extract_path_candidates_windows_and_relative():
    text = r"请读取 D:\repo\a.py 和 ../secret.txt"
    paths = extract_path_candidates(text)
    assert r"D:\repo\a.py" in paths
    assert "../secret.txt" in paths
