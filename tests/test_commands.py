from feishu_claudecode_qiao.commands import parse_command, Command


def test_plain_text_is_not_command():
    cmd = parse_command("hello world")
    assert not cmd.is_command
    assert cmd.args == "hello world"


def test_help_command():
    cmd = parse_command("/help")
    assert cmd.is_command
    assert cmd.name == "help"


def test_ask_with_args():
    cmd = parse_command("/ask what is this")
    assert cmd.is_command
    assert cmd.name == "ask"
    assert cmd.args == "what is this"


def test_unknown_command_still_parsed():
    cmd = parse_command("/unknown")
    assert cmd.is_command
    assert cmd.name == "unknown"
