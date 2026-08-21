from feishu_claudecode_qiao.tasks.local_tool import (
    LocalToolConfig,
    LocalToolHealthResult,
)
from feishu_claudecode_qiao.local_tool_health import LocalToolHealthMonitor


class FakeAudit:
    def __init__(self):
        self.calls = []

    def write(self, event, **fields):
        self.calls.append((event, fields))


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


def test_health_monitor_records_tls_failure_without_refreshing():
    tool = LocalToolConfig(
        name="bi_code_query",
        health_command=["node", "query-logistics-codes.js", "--health"],
        health_interval_seconds=900,
        refresh_command=["node", "query-logistics-codes.js", "--refresh-auth"],
    )
    calls = []

    class FakeRunner:
        def run_health_check(self, configured_tool):
            calls.append(("health", configured_tool.name))
            return LocalToolHealthResult(
                ok=False,
                tool_name=configured_tool.name,
                status="tls_error",
                message="BI API TLS 证书校验失败",
            )

        def run_refresh(self, configured_tool):
            calls.append(("refresh", configured_tool.name))
            raise AssertionError("TLS 故障不应触发 BI 登录刷新")

    audit = FakeAudit()
    monitor = LocalToolHealthMonitor([tool], FakeRunner(), FakeLogger(), audit)

    monitor.check_once(tool)

    assert calls == [("health", "bi_code_query")]
    assert audit.calls == [(
        "local_tool_health",
        {
            "tool": "bi_code_query",
            "status": "tls_error",
            "ok": False,
            "message": "BI API TLS 证书校验失败",
        },
    )]


def test_health_monitor_refreshes_once_then_rechecks_auth_expiration():
    tool = LocalToolConfig(
        name="bi_code_query",
        health_command=["node", "query-logistics-codes.js", "--health"],
        health_interval_seconds=900,
        refresh_command=["node", "query-logistics-codes.js", "--refresh-auth"],
        refresh_cooldown_seconds=1800,
    )
    calls = []

    class FakeRunner:
        def run_health_check(self, configured_tool):
            calls.append("health")
            if calls.count("health") == 1:
                return LocalToolHealthResult(
                    ok=False,
                    tool_name=configured_tool.name,
                    status="auth_expired",
                    message="BI 鉴权已失效",
                )
            return LocalToolHealthResult(
                ok=True,
                tool_name=configured_tool.name,
                status="ok",
                message="BI API 联通正常",
            )

        def run_refresh(self, configured_tool):
            calls.append("refresh")
            return LocalToolHealthResult(
                ok=True,
                tool_name=configured_tool.name,
                status="refreshed",
                message="BI 鉴权已刷新",
            )

    audit = FakeAudit()
    monitor = LocalToolHealthMonitor([tool], FakeRunner(), FakeLogger(), audit)

    monitor.check_once(tool, now=1_000)

    assert calls == ["health", "refresh", "health"]
    assert [event for event, _ in audit.calls] == [
        "local_tool_health",
        "local_tool_auth_refresh",
        "local_tool_health",
    ]
