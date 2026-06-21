import json
import subprocess
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


def test_parse_bi_output_includes_single_record_details():
    payload = {
        "success": True,
        "total": 1,
        "mode": "code",
        "results": [
            {
                "code": "26021312404478",
                "found": True,
                "rows": [
                    {
                        "warehouse": "上海仓",
                        "channel": "天猫",
                        "productCode": "BJGJ107",
                        "productName": "古井贡酒经典45度500ml",
                        "outboundTime": "2026-06-17",
                        "sourceOrderNo": "Q202606160035-6/8",
                        "wmsPickingNo": "WD2606160000190",
                        "remark": "天猫-华东嘉兴集货仓-整箱",
                    }
                ],
            }
        ],
    }

    result = parse_bi_output(json.dumps(payload, ensure_ascii=False))

    assert result.ok is True
    assert "物流码：26021312404478" in result.summary
    assert "仓库：上海仓" in result.summary
    assert "渠道：天猫" in result.summary
    assert "产品名称：古井贡酒经典45度500ml" in result.summary
    assert "来源单号：Q202606160035-6/8" in result.summary
    assert "WMS配货单号：WD2606160000190" in result.summary
    assert "备注：天猫-华东嘉兴集货仓-整箱" in result.summary


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
    assert calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["errors"] == "replace"


def test_bi_runner_returns_error_on_timeout(tmp_path, monkeypatch):
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    script = tool_dir / "query-logistics-codes.js"
    script.write_text("console.log('ok')", encoding="utf-8")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr("feishu_claudecode_qiao.tasks.bi_logistics.subprocess.run", fake_run)

    runner = BiLogisticsRunner(tool_dir=tool_dir)
    result = runner.run(BiLogisticsRequest(codes=["26021312404478"]), timeout_seconds=1)

    assert result.ok is False
    assert "超时" in result.error
    assert "26021312404478" in result.error
