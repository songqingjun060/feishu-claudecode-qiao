from feishu_claudecode_qiao.task_router import TaskContext, TaskRouter
from feishu_claudecode_qiao.tasks.local_tool import LocalToolConfig


def test_task_router_matches_configured_local_tool():
    tool = LocalToolConfig(
        name="sample_lookup",
        keywords=["查询"],
        match_patterns=[r"\b[A-Z]{2}\d{4}\b"],
        command=["sample.exe", "{matches}"],
    )

    result = TaskRouter([tool]).match(
        "帮我查询 AB1234 和 CD5678",
        TaskContext(chat_id="oc_1", recent_files=[]),
    )

    assert result is not None
    assert result.task_kind == "local_tool"
    assert result.tool == tool
    assert result.params["matches"] == ["AB1234", "CD5678"]


def test_task_router_ignores_unconfigured_plain_number():
    tool = LocalToolConfig(
        name="sample_lookup",
        keywords=["查询"],
        match_patterns=[r"\b[A-Z]{2}\d{4}\b"],
        command=["sample.exe", "{matches}"],
    )

    result = TaskRouter([tool]).match(
        "今天 26022711053673 这个数字是什么意思",
        TaskContext(chat_id="oc_1", recent_files=[]),
    )

    assert result is None


def test_task_router_without_tools_matches_nothing():
    result = TaskRouter().match(
        "查询 AB1234",
        TaskContext(chat_id="oc_1", recent_files=[]),
    )

    assert result is None
