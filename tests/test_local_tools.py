import json
import subprocess

from feishu_claudecode_qiao.tasks.local_tool import (
    LocalToolConfig,
    LocalToolRequest,
    LocalToolRunner,
    parse_local_tool_output,
)


def test_parse_local_tool_output_extracts_summary_and_attachment_path():
    tool = LocalToolConfig(name="sample")
    payload = {
        "ok": True,
        "summary": "查询完成，共 1 条。",
        "attachment_path": "D:/output/result.xlsx",
    }

    result = parse_local_tool_output(json.dumps(payload, ensure_ascii=False), tool)

    assert result.ok is True
    assert result.tool_name == "sample"
    assert result.summary == "查询完成，共 1 条。"
    assert result.attachment_path == "D:/output/result.xlsx"


def test_local_tool_runner_renders_command_template(tmp_path, monkeypatch):
    calls = []
    tool = LocalToolConfig(
        name="sample",
        command=["tool.exe", "--ids", "{matches}", "--text", "{content}"],
        cwd=str(tmp_path),
    )

    class Completed:
        returncode = 0
        stdout = json.dumps({"ok": True, "summary": "done"})
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr("feishu_claudecode_qiao.tasks.local_tool.subprocess.run", fake_run)

    result = LocalToolRunner().run(
        LocalToolRequest(tool=tool, matches=["A001", "A002"], content="查一下 A001 A002")
    )

    assert result.ok is True
    assert result.summary == "done"
    assert calls[0][0] == ["tool.exe", "--ids", "A001,A002", "--text", "查一下 A001 A002"]
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "replace"


def test_local_tool_runner_returns_error_on_timeout(tmp_path, monkeypatch):
    tool = LocalToolConfig(name="sample", command=["tool.exe"], cwd=str(tmp_path), timeout_seconds=1)

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr("feishu_claudecode_qiao.tasks.local_tool.subprocess.run", fake_run)

    result = LocalToolRunner().run(LocalToolRequest(tool=tool, matches=["A001"], content="查一下"))

    assert result.ok is False
    assert "超时" in result.error
    assert "sample" in result.error
