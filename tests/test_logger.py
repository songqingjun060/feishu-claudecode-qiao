import logging

from feishu_claudecode_qiao.logger import setup_logging


def test_setup_logging_creates_new_handlers(tmp_path):
    logger, _ = setup_logging(str(tmp_path), "INFO")
    old_handlers = list(logger.handlers)
    setup_logging(str(tmp_path), "INFO")

    # Old handlers should be removed from the logger
    for handler in old_handlers:
        assert handler not in logger.handlers
    # New handlers should exist
    assert len(logger.handlers) >= 2


def test_message_logger_can_mirror_to_console(tmp_path):
    _, message_logger = setup_logging(str(tmp_path), "INFO", mirror_messages_to_console=True)

    assert any(isinstance(handler, logging.StreamHandler) for handler in message_logger.handlers)


def test_message_logger_can_stay_file_only(tmp_path):
    _, message_logger = setup_logging(str(tmp_path), "INFO", mirror_messages_to_console=False)

    stream_handlers = [
        handler
        for handler in message_logger.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ]
    assert stream_handlers == []
