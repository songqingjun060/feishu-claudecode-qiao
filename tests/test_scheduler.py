from feishu_claudecode_qiao.scheduler import ChatScheduler, QueuePolicy


def test_scheduler_starts_first_run_and_queues_next_message():
    scheduler = ChatScheduler(QueuePolicy(queue_notice_after_seconds=5))

    first = scheduler.enqueue(chat_id="oc_1", message_id="om_1", sender_id="ou_1", content="分析文件")
    second = scheduler.enqueue(chat_id="oc_1", message_id="om_2", sender_id="ou_1", content="补充说明")

    assert first.started is True
    assert first.run is not None
    assert first.queue_position == 0
    assert second.started is False
    assert second.queue_position == 1
    assert scheduler.status("oc_1").active_run_id == first.run.run_id
    assert scheduler.status("oc_1").queued_count == 1


def test_scheduler_finishes_run_and_starts_next_queued_message():
    scheduler = ChatScheduler()
    first = scheduler.enqueue(chat_id="oc_1", message_id="om_1", sender_id="ou_1", content="任务一")
    scheduler.enqueue(chat_id="oc_1", message_id="om_2", sender_id="ou_1", content="任务二")

    next_run = scheduler.finish(first.run.run_id)

    assert next_run is not None
    assert next_run.message_ids == ["om_2"]
    assert scheduler.status("oc_1").active_run_id == next_run.run_id
    assert scheduler.status("oc_1").queued_count == 0


def test_scheduler_cancel_marks_active_run_cancel_requested():
    scheduler = ChatScheduler()
    started = scheduler.enqueue(chat_id="oc_1", message_id="om_1", sender_id="ou_1", content="长任务")

    cancelled = scheduler.cancel("oc_1")

    assert cancelled is True
    assert started.run.cancel_requested is True
    assert scheduler.status("oc_1").active_status == "cancelling"


def test_scheduler_notice_threshold_avoids_immediate_busy_spam():
    scheduler = ChatScheduler(QueuePolicy(queue_notice_after_seconds=5))
    scheduler.enqueue(chat_id="oc_1", message_id="om_1", sender_id="ou_1", content="任务一", now=100.0)
    scheduler.enqueue(chat_id="oc_1", message_id="om_2", sender_id="ou_1", content="任务二", now=101.0)

    assert scheduler.should_notice_queue("oc_1", now=104.0) is False
    assert scheduler.should_notice_queue("oc_1", now=107.0) is True
    assert scheduler.should_notice_queue("oc_1", now=108.0) is False
