import json
from feishu_claudecode_qiao.audit import AuditLogger


def test_audit_write(tmp_path):
    path = tmp_path / "audit.jsonl"
    logger = AuditLogger(path)
    logger.write("message_received", chat_id="c1", sender="u1")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "message_received"
    assert record["chat_id"] == "c1"
