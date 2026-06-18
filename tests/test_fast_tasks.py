import json
from pathlib import Path

from feishu_claudecode_qiao.tasks.bi_logistics import (
    BiLogisticsRequest,
    BiLogisticsRunner,
    parse_bi_output,
)


def test_parse_bi_output_extracts_excel_path():
    payload = {
        "ok": True,
        "excelFilePath": "C:/Users/tanks/.openclaw/media/物流码查询结果.xlsx",
    }

    result = parse_bi_output(json.dumps(payload, ensure_ascii=False))

    assert result.ok is True
    assert result.excel_path.endswith("物流码查询结果.xlsx")


def test_bi_runner_invokes_source_query(tmp_path, monkeypatch):
    calls = []
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    script = tool_dir / "query-logistics-codes.js"
    script.write_text("console.log('ok')", encoding="utf-8")
    output = tmp_path / "result.xlsx"
    output.write_text("xlsx", encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = json.dumps({"ok": True, "excelFilePath": str(output)})
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr("feishu_claudecode_qiao.tasks.bi_logistics.subprocess.run", fake_run)

    runner = BiLogisticsRunner(tool_dir=tool_dir)
    result = runner.run(BiLogisticsRequest(sources=["Q202605270017-5/7"]))

    assert result.ok is True
    assert Path(result.excel_path) == output
    args = calls[0][0]
    assert args[:2] == ["node", str(script)]
    assert "--source" in args
    assert "Q202605270017-5/7" in args
