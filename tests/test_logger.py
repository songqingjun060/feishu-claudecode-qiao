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
