import time
from threading import Event

from feishu_claudecode_qiao.event_dispatcher import ChatEventDispatcher


def make_event(chat_id: str, message_id: str) -> dict:
    return {
        "event": {
            "message": {
                "chat_id": chat_id,
                "message_id": message_id,
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
