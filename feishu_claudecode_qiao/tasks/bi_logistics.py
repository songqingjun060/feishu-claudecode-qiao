from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_TOOL_DIR = Path("D:/BI-wuliumachaxun")


@dataclass(frozen=True)
class BiLogisticsRequest:
    codes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    wms_orders: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BiLogisticsResult:
    ok: bool
    summary: str = ""
    excel_path: str = ""
    raw_output: str = ""
    error: str = ""


class BiLogisticsRunner:
    def __init__(self, tool_dir: str | Path = DEFAULT_TOOL_DIR) -> None:
        self.tool_dir = Path(tool_dir).expanduser().resolve()

    def run(self, request: BiLogisticsRequest, *, timeout_seconds: int = 180) -> BiLogisticsResult:
        script = self.tool_dir / "query-logistics-codes.js"
        exe = self.tool_dir / "BI-wuliumachaxun.exe"
        if script.exists():
            args = ["node", str(script)]
        elif exe.exists():
            args = [str(exe)]
        else:
            return BiLogisticsResult(
                ok=False,
                error=f"未找到 BI 物流码查询工具: {self.tool_dir}",
            )

        if request.sources:
            args.extend(["--source", ",".join(request.sources)])
        elif request.wms_orders:
            args.extend(["--wms", ",".join(request.wms_orders)])
        elif request.codes:
            args.extend(["--codes", ",".join(request.codes)])
        else:
            return BiLogisticsResult(ok=False, error="未提供可查询的物流码、来源单号或 WMS 配货单号。")

        try:
            completed = subprocess.run(
                args,
                cwd=self.tool_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            target = ",".join(request.codes or request.sources or request.wms_orders)
            return BiLogisticsResult(
                ok=False,
                error=f"BI 查询工具超时（{timeout_seconds} 秒）：{target}",
            )
        except (OSError, UnicodeError) as exc:
            return BiLogisticsResult(
                ok=False,
                error=f"BI 查询工具调用失败：{exc}",
            )
        output = (completed.stdout or "").strip()
        if completed.returncode != 0:
            return BiLogisticsResult(
                ok=False,
                raw_output=output,
                error=(completed.stderr or output or f"BI 查询工具退出码 {completed.returncode}").strip(),
            )
        result = parse_bi_output(output)
        if not result.ok:
            return result
        return result


def parse_bi_output(output: str) -> BiLogisticsResult:
    text = (output or "").strip()
    if not text:
        return BiLogisticsResult(ok=False, error="BI 查询工具没有输出。")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return BiLogisticsResult(ok=True, summary=text, raw_output=text)

    excel_path = str(payload.get("excelFilePath") or "")
    ok = payload.get("ok", payload.get("success", True)) is not False
    if not ok:
        return BiLogisticsResult(
            ok=False,
            raw_output=text,
            error=str(payload.get("error") or payload.get("message") or "BI 查询失败"),
        )
    summary = _summarize_payload(payload)
    return BiLogisticsResult(
        ok=True,
        summary=summary,
        excel_path=excel_path,
        raw_output=text,
    )


def _summarize_payload(payload: dict) -> str:
    mode = payload.get("mode", "code")
    results = payload.get("results") or []
    found = 0
    total = len(results)
    for item in results:
        if item.get("found"):
            found += 1
    summary = f"BI 物流码查询完成：模式 {mode}，共 {total} 条，查询到 {found} 条。" if total else "BI 物流码查询完成。"
    detail = _format_payload_details(payload)
    if detail:
        return f"{summary}\n\n{detail}"
    return summary


def _format_payload_details(payload: dict) -> str:
    mode = str(payload.get("mode") or "code")
    results = payload.get("results") or []
    if mode == "source":
        return _format_source_results(results)
    if mode == "wms":
        return _format_wms_results(results)
    return _format_code_results(results)


def _format_code_results(results: list[dict]) -> str:
    sections: list[str] = []
    for result in results:
        code = str(result.get("code") or "")
        if result.get("error"):
            sections.append(f"物流码：{code}\n查询失败：{result.get('error')}")
            continue
        rows = result.get("rows") or []
        if not result.get("found") or not rows:
            sections.append(f"物流码：{code}\n未查询到结果")
            continue
        for index, row in enumerate(rows, start=1):
            title = f"物流码：{code}" if len(rows) == 1 else f"物流码：{code}（结果 {index}）"
            sections.append(
                "\n".join(
                    [
                        title,
                        f"仓库：{row.get('warehouse') or ''}",
                        f"渠道：{row.get('channel') or ''}",
                        f"产品编码：{row.get('productCode') or ''}",
                        f"产品名称：{row.get('productName') or ''}",
                        f"出库时间：{row.get('outboundTime') or ''}",
                        f"来源单号：{row.get('sourceOrderNo') or ''}",
                        f"WMS配货单号：{row.get('wmsPickingNo') or ''}",
                        f"备注：{row.get('remark') or ''}",
                    ]
                )
            )
    return "\n\n".join(sections)


def _format_source_results(results: list[dict]) -> str:
    sections: list[str] = []
    for result in results:
        source = str(result.get("source") or "")
        if result.get("error"):
            sections.append(f"来源单号：{source}\n查询失败：{result.get('error')}")
            continue
        codes = [str(code) for code in result.get("logisticsCodes", []) if code]
        if not result.get("found") or not codes:
            sections.append(f"来源单号：{source}\n未查询到结果")
            continue
        sections.append("\n".join([f"来源单号：{source}", f"共 {len(codes)} 个物流码", *codes]))
    return "\n\n".join(sections)


def _format_wms_results(results: list[dict]) -> str:
    sections: list[str] = []
    for result in results:
        wms_order = str(result.get("wmsOrder") or "")
        if result.get("error"):
            sections.append(f"WMS配货单号：{wms_order}\n查询失败：{result.get('error')}")
            continue
        codes = [str(code) for code in result.get("logisticsCodes", []) if code]
        if not result.get("found") or not codes:
            sections.append(f"WMS配货单号：{wms_order}\n未查询到结果")
            continue
        sections.append("\n".join([f"WMS配货单号：{wms_order}", f"共 {len(codes)} 个物流码", *codes]))
    return "\n\n".join(sections)
