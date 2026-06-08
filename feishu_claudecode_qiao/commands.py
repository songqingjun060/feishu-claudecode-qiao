from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Command:
    name: str
    args: str = ""
    is_command: bool = False


SUPPORTED_COMMANDS = {
    "help",
    "rules",
    "context",
    "summary",
    "compact",
    "new",
    "reset",
    "workspace",
    "paths",
    "permission",
    "ask",
}


def parse_command(text: str) -> Command:
    stripped = text.strip()
    stripped = re.sub(r"^(?:@\S+\s+)+", "", stripped).strip()
    if not stripped.startswith("/"):
        return Command(name="", args=text, is_command=False)
    head, _, rest = stripped[1:].partition(" ")
    name = head.lower()
    if name not in SUPPORTED_COMMANDS:
        return Command(name=name, args=rest.strip(), is_command=True)
    return Command(name=name, args=rest.strip(), is_command=True)
