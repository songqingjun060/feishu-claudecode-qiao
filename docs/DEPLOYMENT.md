# Deployment Guide

This guide is for a clean local/team deployment.

## 1. Prepare Python And Claude CLI

Requirements:

- Python 3.10+
- Claude CLI available as `claude`
- Feishu app credentials

Install:

```bash
python -m pip install -e ".[dev,voice]"
```

If audio is not needed, use:

```bash
python -m pip install -e ".[dev]"
```

## 2. Configure Feishu

Create or reuse a Feishu app and configure:

- Message receive event subscription.
- Send message permission.
- Reply message permission.
- Message reaction permission.
- Message resource read/download permission.
- File upload permission.
- `im:message.group_msg` if using "send audio first, then @bot".

After permission changes, publish the app and restart the bridge.

## 3. Configure The Bridge

Copy:

```bash
copy config.example.toml config.toml
```

Edit:

```toml
[feishu]
app_id = "cli_xxxxx"
app_secret = "xxxxx"

[claude]
command = "claude"
work_dir = "D:/your/workspace"
permission_mode = "safe"

[bridge]
data_dir = "./data"
require_mention_in_group = true
bot_display_name = "your-bot-display-name"
personal_permission_profile = "admin"
bot_owner_id = "your-feishu-open-id"
bot_admins = []

[security]
allowed_paths = ["D:/your/workspace"]
```

In groups with more than one bot, set `bot_display_name` to this bot's visible Feishu name. Group messages are processed only when the current bot is mentioned by ID or by an exact display-name match.

Personal chats use `personal_permission_profile`. Group rule changes apply only to the current group and are controlled by bot ownership: if `bot_admins` is empty, `bot_owner_id` is the only user allowed to change group rules; if `bot_admins` is set, only listed users can change group rules.

For trusted maintenance groups, create a rule file under `data/rules/<chat_id>.json` after the bridge has run once:

```json
{
  "workspace": "D:/your/workspace",
  "allowed_paths": ["D:/your/workspace"],
  "permission_profile": "safe",
  "session_mode": "shared_chat"
}
```

## 4. Media Handling

Images, files, and videos are downloaded by the bridge and passed to Claude Code as local file paths. Configure Claude Code and local tools for content analysis; the bridge does not require a separate image-analysis API.

## 5. Run Self-Check

```bash
python -m feishu_claudecode_qiao --config config.toml --doctor
python -m pytest -q
```

## 6. Start

Start or restart the lark-cli WebSocket subscriber. Use the profile that matches this Feishu app:

```bash
python start_ws.py restart --config config.toml --profile qiao-test
python start_ws.py status --config config.toml
```

Foreground:

```bash
python -m feishu_claudecode_qiao --config config.toml
```

Windows one-window foreground mode:

```powershell
.\run_foreground.ps1 -Config config.realtest.toml -Profile qiao-test
```

Windows one-command start or restart:

```powershell
.\start_all.ps1
.\start_all.ps1 -Restart
.\start_all.ps1 -Restart -Foreground
```

Background on Windows PowerShell:

```powershell
Start-Process -FilePath python -ArgumentList @('-m','feishu_claudecode_qiao','--config','config.toml') -WorkingDirectory (Get-Location) -WindowStyle Hidden
```

Status:

```bash
python -m feishu_claudecode_qiao --config config.toml --status
```

Stop:

```bash
python start_ws.py stop --config config.toml
python -m feishu_claudecode_qiao --config config.toml --stop
```

## 7. Smoke Tests

In a Feishu group:

1. Send `@your-bot-display-name 测试连接`.
2. Confirm the bot adds a temporary reaction and removes it after reply.
3. Confirm the reply quotes your message and mentions you.
4. Send an image and mention the bot; confirm Claude receives the local image path.
5. Send a short audio message, then mention the bot or say `@your-bot-display-name 读上一条消息`.
6. Ask the bot to upload a small allowed local file.

## 8. Upgrade

Stop the bridge, replace source files, reinstall if dependencies changed, then start again:

```bash
python -m feishu_claudecode_qiao --config config.toml --stop
python -m pip install -e ".[dev,voice]"
python -m feishu_claudecode_qiao --config config.toml
```

Runtime data in `data/` can usually be kept across upgrades.
