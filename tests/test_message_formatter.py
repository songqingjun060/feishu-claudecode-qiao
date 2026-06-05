import json

import pytest

from feishu_claudecode_qiao.message_formatter import (
    auto_detect_format,
    markdown_to_card,
    _detect_header_color,
)


def test_plain_text():
    content, msg_type = auto_detect_format("你好，这是一条普通消息")
    assert msg_type == "text"
    assert "你好" in content


def test_markdown_heading():
    content, msg_type = auto_detect_format("# 标题\n\n这是一段内容")
    assert msg_type == "interactive"
    assert "标题" in content


def test_markdown_bold():
    content, msg_type = auto_detect_format("**粗体文字**")
    assert msg_type == "interactive"
    assert "粗体" in content


def test_markdown_code_block():
    content, msg_type = auto_detect_format("```python\nprint('hello')\n```")
    assert msg_type == "interactive"
    assert "hello" in content


def test_markdown_table():
    content, msg_type = auto_detect_format("| a | b |\n|---|---|\n| 1 | 2 |")
    assert msg_type == "interactive"
    assert "a" in content


def test_card_json_structure():
    card_str = markdown_to_card("# 测试标题\n\n内容")
    card = json.loads(card_str)
    assert "config" in card
    assert card["config"]["wide_screen_mode"] is True
    assert "header" in card
    assert "template" in card["header"]
    assert "title" in card["header"]
    assert "elements" in card
    assert len(card["elements"]) > 0
    assert card["elements"][0]["tag"] == "div"
    assert card["elements"][0]["text"]["tag"] == "lark_md"


def test_card_sentiment_red():
    assert _detect_header_color("发生错误") == "red"
    assert _detect_header_color("操作失败") == "red"
    assert _detect_header_color("严重问题") == "red"


def test_card_sentiment_green():
    assert _detect_header_color("操作成功") == "green"
    assert _detect_header_color("任务完成") == "green"
    assert _detect_header_color("测试通过") == "green"
