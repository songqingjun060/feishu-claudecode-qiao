from feishu_claudecode_qiao.task_router import TaskContext, TaskRouter


def test_task_router_matches_bi_logistics_source_order():
    result = TaskRouter().match(
        "Q202605270017-5/7 查询BI物流码",
        TaskContext(chat_id="oc_1", recent_files=[]),
    )

    assert result is not None
    assert result.task_kind == "bi_logistics"
    assert result.confidence >= 0.8
    assert result.params["sources"] == ["Q202605270017-5/7"]


def test_task_router_matches_bi_logistics_codes():
    result = TaskRouter().match(
        "查询物流码 26022711053673, 26022710110073",
        TaskContext(chat_id="oc_1", recent_files=[]),
    )

    assert result is not None
    assert result.params["codes"] == ["26022711053673", "26022710110073"]


def test_task_router_ignores_low_confidence_plain_number():
    result = TaskRouter().match(
        "今天 26022711053673 这个数字是什么意思",
        TaskContext(chat_id="oc_1", recent_files=[]),
    )

    assert result is None
