import time
from threading import Event, Lock

from feishu_claudecode_qiao.event_dispatcher import ChatEventDispatcher


def make_event(chat_id: str, message_id: str, message_type: str = "text") -> dict:
    return {
        "event": {
            "message": {
                "chat_id": chat_id,
                "message_id": message_id,
                "message_type": message_type,
            }
        }
    }


def test_same_chat_events_are_processed_serially():
    first_started = Event()
    first_can_finish = Event()
    second_started = Event()
    processed = []

    def process(event):
        message_id = event["event"]["message"]["message_id"]
        processed.append(message_id)
        if message_id == "om_1":
            first_started.set()
            first_can_finish.wait(timeout=2)
        if message_id == "om_2":
            second_started.set()

    dispatcher = ChatEventDispatcher(process)
    try:
        dispatcher.dispatch(make_event("oc_1", "om_1"))
        assert first_started.wait(timeout=1)

        dispatcher.dispatch(make_event("oc_1", "om_2"))
        time.sleep(0.1)
        assert not second_started.is_set()

        first_can_finish.set()
        assert dispatcher.wait_idle(timeout=2)
        assert processed == ["om_1", "om_2"]
    finally:
        dispatcher.stop(timeout=2)


def test_different_chats_can_process_while_one_chat_is_blocked():
    first_started = Event()
    first_can_finish = Event()
    second_started = Event()

    def process(event):
        message = event["event"]["message"]
        if message["message_id"] == "om_1":
            first_started.set()
            first_can_finish.wait(timeout=2)
        if message["message_id"] == "om_2":
            second_started.set()

    dispatcher = ChatEventDispatcher(process)
    try:
        dispatcher.dispatch(make_event("oc_1", "om_1"))
        assert first_started.wait(timeout=1)

        dispatcher.dispatch(make_event("oc_2", "om_2"))
        assert second_started.wait(timeout=1)

        first_can_finish.set()
        assert dispatcher.wait_idle(timeout=2)
    finally:
        dispatcher.stop(timeout=2)


def test_same_chat_events_can_be_coalesced_within_window():
    processed = []

    def coalesce(events):
        merged = make_event("oc_1", "+".join(
            event["event"]["message"]["message_id"] for event in events
        ))
        merged["merged_count"] = len(events)
        return merged

    dispatcher = ChatEventDispatcher(
        lambda event: processed.append(event),
        coalesce=coalesce,
        coalesce_window_seconds=0.05,
    )
    try:
        dispatcher.dispatch(make_event("oc_1", "om_1"))
        dispatcher.dispatch(make_event("oc_1", "om_2"))

        assert dispatcher.wait_idle(timeout=2)
        assert [event["event"]["message"]["message_id"] for event in processed] == ["om_1+om_2"]
        assert processed[0]["merged_count"] == 2
    finally:
        dispatcher.stop(timeout=2)


def test_callable_coalesce_window_uses_message_type_and_records_wait_time():
    processed = []
    processed_lock = Lock()

    def coalesce(events):
        first_message = events[0]["event"]["message"]
        merged = make_event(
            first_message["chat_id"],
            "+".join(event["event"]["message"]["message_id"] for event in events),
            first_message["message_type"],
        )
        merged["merged_ids"] = [
            event["event"]["message"]["message_id"] for event in events
        ]
        return merged

    def window_for(event):
        message_type = event["event"]["message"]["message_type"]
        return 0.05 if message_type == "text" else 0.30

    def process(event):
        with processed_lock:
            processed.append(event)

    dispatcher = ChatEventDispatcher(
        process,
        coalesce=coalesce,
        coalesce_window_seconds=window_for,
    )
    try:
        dispatcher.dispatch(make_event("oc_text", "om_t1", "text"))
        time.sleep(0.12)
        dispatcher.dispatch(make_event("oc_text", "om_t2", "text"))

        dispatcher.dispatch(make_event("oc_image", "om_i1", "image"))
        time.sleep(0.12)
        dispatcher.dispatch(make_event("oc_image", "om_i2", "image"))

        assert dispatcher.wait_idle(timeout=3)

        with processed_lock:
            text_groups = [
                event["merged_ids"]
                for event in processed
                if event["event"]["message"]["chat_id"] == "oc_text"
            ]
            image_groups = [
                event["merged_ids"]
                for event in processed
                if event["event"]["message"]["chat_id"] == "oc_image"
            ]

        assert text_groups == [["om_t1"], ["om_t2"]]
        assert image_groups == [["om_i1", "om_i2"]]

        text_wait_ms = dispatcher.last_coalesce_wait_ms("oc_text")
        image_wait_ms = dispatcher.last_coalesce_wait_ms("oc_image")
        assert 40 <= text_wait_ms < 200
        assert image_wait_ms >= 250
        assert image_wait_ms > text_wait_ms
    finally:
        dispatcher.stop(timeout=2)
