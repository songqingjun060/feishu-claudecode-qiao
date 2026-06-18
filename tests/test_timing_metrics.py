import json
import time

from feishu_claudecode_qiao.audit import AuditLogger
from feishu_claudecode_qiao.timing import RunTiming


def test_run_timing_records_stage_durations_in_order():
    timing = RunTiming("run_1")

    timing.mark("received")
    time.sleep(0.001)
    timing.mark("queued")
    time.sleep(0.001)
    timing.mark("claude_started")

    stages = timing.stage_ms()

    assert list(stages) == ["received_to_queued", "queued_to_claude_started"]
    assert stages["received_to_queued"] >= 0
    assert stages["queued_to_claude_started"] >= 0


def test_audit_write_timing_event(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)
    timing = RunTiming("run_1")
    timing.mark("received")
    timing.mark("completed")

    logger.write_timing(
        timing,
        chat_id="oc_1",
        message_id="om_1",
        session_key="chat:oc_1",
    )

    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["action"] == "message_timing"
    assert record["run_id"] == "run_1"
    assert record["chat_id"] == "oc_1"
    assert record["message_id"] == "om_1"
    assert "received_to_completed" in record["stage_ms"]
