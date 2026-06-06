# Troubleshooting

This document records common deployment issues and the verified fixes.

## Bot Does Not Reply In Group

Check:

- The Feishu app receives `im.message.receive_v1` events.
- The group message mentions this exact bot when `require_mention_in_group = true`.
- `bot_display_name` exactly matches the bot name shown in Feishu if mention IDs do not match the app ID.
- `bridge.pid` points to a running Python process.
- `data/logs/feishu_ws_events.jsonl` is growing.
- `data/logs/bridge.log` has no token or send-message errors.
- `python start_ws.py status --config config.toml` shows the lark-cli subscriber is running with the profile for this Feishu app.

Useful commands:

```bash
python -m feishu_claudecode_qiao --config config.toml --status
python -m feishu_claudecode_qiao --config config.toml --doctor
python start_ws.py status --config config.toml
```

If a different bot is mentioned and this bridge replies, upgrade to a version with exact mention matching. Older builds accepted any Feishu mention with `mentioned_type = bot`.

If this bot does not reply when mentioned, set:

```toml
[bridge]
require_mention_in_group = true
bot_display_name = "your-bot-display-name"
```

## Old Messages Are Replied After Restart

The bridge starts reading the event file at the current end offset. If old messages are still being replied to, confirm the running process is the latest version and restart it:

```bash
python -m feishu_claudecode_qiao --config config.toml --stop
python -m feishu_claudecode_qiao --config config.toml
```

## Group Reply Does Not Mention Or Quote The Sender

The bridge should send group replies through:

```text
POST /open-apis/im/v1/messages/{message_id}/reply
```

Text replies are prefixed with a Feishu at-mention. Card replies add a mention at the top of the card. File replies quote the source message but cannot embed text in the file payload.

If quote/mention is missing, confirm you are running a version with the `_send_event_reply` path and the Feishu app has reply-message permission.

## Image Handling

Images are downloaded by the bridge and passed to Claude Code as local file paths. If image analysis fails, check that the image resource was downloaded and that Claude Code can access the saved path under the current workspace/allowed_paths boundary.


## Audio Works In Private Chat But Not In Group

Check:

- The Feishu app can receive group audio events.
- The app has permission to download message resources.
- `faster-whisper` and `imageio-ffmpeg` are installed for audio support:

```bash
python -m pip install -e ".[voice]"
```

For the workflow "send audio first, then @bot", the app also needs:

```text
im:message.group_msg
```

Without it, the bridge cannot fetch recent group history when the original audio event was not pushed to the bridge.

## File Upload Does Not Work

The bridge uploads local files only when all conditions are true:

- The message clearly asks to send/upload a local file.
- The local file path or desktop filename fragment can be resolved.
- The path is allowed by the effective group/member rule.
- The file exists and does not exceed `max_upload_mb`.
- The Feishu app has file upload and send message permissions.

Runtime files are never copied from the user's machine automatically unless the bridge can resolve and validate the path.

## Claude Says It Cannot Read Local Files

There are two independent permission layers:

- Bridge path rules decide whether a path can be passed to Claude.
- Claude CLI permission mode decides whether Claude can read or edit files.

For trusted local testing, `permission_profile = "admin"` maps to Claude CLI `bypassPermissions`. For production, prefer `safe` or `readonly`.

## Missing Claude Session

If Claude returns "No conversation found with session ID", the bridge clears the saved session and retries once without the old session. If this repeats, use:

```text
/reset
```

or delete the relevant entry in `data/sessions.json` while the bridge is stopped.

## Logs To Check

```text
data/logs/bridge.log       service, token, API, Claude, media processing
data/logs/messages.log     incoming and outgoing message flow
data/logs/audit.jsonl      security decisions and reply events
```

Do not share logs publicly; they can contain chat content and local paths.
