# Tested Flows

Last local verification: 2026-06-05

Automated tests:

```text
129 passed
```

Real Feishu deployment flows verified:

- Text group message to Claude.
- Group reply quotes the source message and mentions sender.
- Temporary reaction is added on receipt and removed after completion.
- Local desktop Markdown file upload to group after rule validation.
- Personal audio transcription.
- Group audio transcription when user sends audio first and then mentions the bot.
- Image download and Claude Code local-path handoff.
- Bridge restart starts from the current event-file end offset and does not replay old messages.
- Stale Claude session id is cleared and retried once.

Known limitations:

- File message payloads can quote the source message but cannot embed an extra textual mention.
- The bridge does not upload arbitrary desktop files unless the message intent is clear and the path passes rule validation.
- `admin` permission profile is suitable only for trusted testing or maintenance.
- Logs can contain chat content and local file paths.
