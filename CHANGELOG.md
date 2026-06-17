# Changelog

## Unreleased

- Added continuous image context: bare image messages are cached without calling Claude, and follow-up text can process recent images together.
- Added multi-image rich-text handling so all image paths are passed to Claude in one request.
- Tightened group mention matching so messages that mention another bot no longer trigger this bridge.
- Documented `bot_display_name` for exact group mention matching in multi-bot groups.
- Added `start_ws.py` to manage the lark-cli event subscriber with an explicit profile per bridge.
- Added `run_foreground.ps1` for one-window foreground bridge operation with background subscriber checks.

## 0.3.0

- Added group replies through Feishu reply endpoint with sender mention.
- Added temporary receive reaction and cleanup after processing.
- Added local file upload from allowed local paths to Feishu chat.
- Added group recent-audio workflow: send audio first, then mention the bot.
- Added Kimi Coding Anthropic-compatible Vision API support.
- Added Vision URL normalization for Anthropic and OpenAI-compatible providers.
- Added restart behavior that starts from the end of the event file to avoid old-message replay.
- Added Claude missing-session retry by clearing stale session id.
- Expanded tests to 129 passing cases.
- Added deployment and troubleshooting documentation.

## 0.2.0

- Added `SessionStore` for session metadata.
- Added automatic session rollover summary support.
- Added effective rule resolution for default, chat, member, and temporary rules.
- Added `permission_profile` mapping to Claude CLI permission modes.
- Added workspace and allowed path enforcement.
- Added risky intent detection and `confirm_policy`.
- Added `/workspace`, `/permission`, `/context`, `/summary`, `/new`, `/reset`, and `/compact`.
- Added audit logs and doctor checks.

## 0.1.0

- Initial Feishu-Claude Code bridge.
