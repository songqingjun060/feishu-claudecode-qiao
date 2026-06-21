from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_TOOL_DIR = Path("C:/Users/tanks/BI-wuliumachaxun")


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
    ok = payload.get("ok", True) is not False
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
    if total:
        return f"BI 物流码查询完成：模式 {mode}，共 {total} 条，查询到 {found} 条。"
    return "BI 物流码查询完成。"
