# Feishu-Claudecode-Qiao

Feishu-Claudecode-Qiao is a Feishu bot bridge for Claude Code. It receives Feishu messages, applies per-chat rules and safety checks, calls Claude CLI, and sends formatted replies back to Feishu.

## 中文快速说明

Feishu-Claudecode-Qiao 是一个“飞书机器人 -> Claude Code CLI”的本地桥接工具。飞书群聊或个人会话里的消息会先进入本桥，桥会按当前会话规则做安全检查，然后调用本机 Claude Code，最后把回复、生成的文件或查询结果发回飞书。

适合场景：

- 在飞书里直接让 Claude Code 查询、分析、生成文件或处理本地项目。
- 给不同群设置不同的工作目录、可访问路径和权限档位。
- 个人会话使用更高权限，群聊默认使用更保守的规则。
- 让 Claude Code 处理飞书上传的图片、音频、PDF、Office、压缩包等文件。

权限逻辑：

- 个人会话默认使用 `bridge.personal_permission_profile`，可信本地部署可以设为 `admin`，对应 Claude Code 的 `bypassPermissions`。
- 群聊规则只对当前群生效，必须在该群里 @ 当前机器人后设置。
- 群规则管理不依赖飞书群管理员。若配置了 `bridge.bot_admins`，只有这些用户能改规则；否则只有 `bridge.bot_owner_id` 能改。
- 群聊建议保持 `require_mention_in_group = true`，避免机器人响应无关消息。
- `allowed_paths` 为空不是“允许全盘”。如需允许读取或上传本地路径，请在规则或配置里明确放行路径。

文件处理说明：

- 桥负责接收飞书文件、下载到本地、把本地文件路径交给 Claude Code。
- PDF、Word、Excel、PPT、压缩包、视频等内容优先由 Claude Code 使用本机工具处理，本桥本身不做重解析。
- Claude Code 生成的本地文件如果符合规则，会自动上传回当前飞书会话。
- 真实运行数据、密钥、日志和本地附件不要提交到 Git；本仓库已通过 `.gitignore` 忽略 `config.toml`、`config.realtest.toml`、`data/`、`data-test/`、日志和压缩包。

最小启动流程：

```powershell
copy config.example.toml config.toml
# 编辑 config.toml，填入飞书 App ID / Secret、Claude 命令、工作目录和权限配置
python -m pip install -e ".[dev,voice]"
python start_ws.py restart --config config.toml --profile qiao-test
python -m feishu_claudecode_qiao --config config.toml
```

Windows 前台运行推荐：

```powershell
.\run_foreground.ps1 -Config config.toml -Profile qiao-test
```

## Current Capabilities

- Text chat with Claude Code.
- Group replies quote the source message and mention the sender.
- A temporary reaction is added when a message is received and removed after processing.
- Markdown output is converted to Feishu interactive cards.
- Per-chat and per-member rules for workspace, allowed paths, permission profile, and session mode.
- Session store with automatic rollover support.
- Local file upload to the current Feishu chat after path and rule validation.
- Feishu image download plus Vision API analysis.
- Feishu audio download plus Whisper transcription.
- "Send audio first, then @bot" group workflow for recent audio.
- Audit logs and doctor self-check.

## Project Structure

```text
feishu_claudecode_qiao/
  bridge.py              Main event loop, Feishu API calls, Claude CLI calls
  config.py              TOML and environment configuration
  security.py            Path whitelist, blocked keywords, risky intent checks
  chat_rules.py          Per-chat rule file management
  rule_engine.py         Default/chat/member rule merging
  session_store.py       Claude session metadata and rollover counters
  commands.py            /help, /rules, /context, /workspace, /permission
  audit.py               JSONL audit log writer
  doctor.py              Environment self-check
  message_formatter.py   Markdown to Feishu card formatter
  logger.py              Rotating log setup
tests/                   Pytest regression tests
```

Runtime data is written under `data_dir`:

```text
data/
  bridge.pid
  sessions.json
  rules/<chat_id>.json
  logs/bridge.log
  logs/messages.log
  logs/audit.jsonl
  images/
  attachments/
```

`data/`, `data-test/`, `config.toml`, and `config.realtest.toml` are intentionally ignored by Git.

## Install

```bash
python -m pip install -e ".[dev]"
```

Optional audio support:

```bash
python -m pip install -e ".[voice]"
```

For development and tests:

```bash
python -m pip install -e ".[dev,voice]"
python -m pytest -q
```

## Configuration

Copy the example config:

```bash
copy config.example.toml config.toml
```

Edit `config.toml`:

```toml
[feishu]
app_id = "cli_xxxxx"
app_secret = "xxxxx"
domain = "https://open.feishu.cn"

[claude]
command = "claude"
work_dir = "."
permission_mode = "safe"

[vision]
provider = "api"
api_key = ""
base_url = ""
model = ""

[whisper]
model = "base"

[bridge]
data_dir = "./data"
log_level = "INFO"
max_upload_mb = 20
require_mention_in_group = true
bot_display_name = "your-bot-display-name"

[security]
allowed_paths = []
blocked_keywords = []
```

Environment variables with the `FEISHUCLAUDECODE_` prefix can override config values.

For group chats, `require_mention_in_group = true` means the bridge only handles messages that mention the current bot. Mention matching is exact: the Feishu mention ID must match the configured app ID, or the mention display name must exactly equal `bot_display_name`. Set `bot_display_name` to the bot name shown in the group, especially when multiple bots are installed in the same group.

## Vision API Notes

Kimi Coding keys should use the Anthropic-compatible endpoint:

```toml
[vision]
provider = "api"
api_key = "your-kimi-coding-key"
base_url = "https://api.kimi.com/coding/"
model = "kimi-for-coding"
```

This bridge normalizes that base URL to:

```text
https://api.kimi.com/coding/v1/messages
```

Do not use `https://api.kimi.com/coding/v1/chat/completions` with a Kimi Coding key for this bridge. That OpenAI-compatible path can return `403 access_terminated_error` for ordinary HTTP calls.

If using a non-Coding OpenAI-compatible vision provider, set `base_url` to the provider's `/v1` base or full `/chat/completions` endpoint.

## Feishu App Permissions

Enable and publish the Feishu app after permission changes. Required capabilities usually include:

- Receive message events.
- Send messages.
- Add and delete message reactions.
- Reply to messages.
- Read message resources for image/audio/file downloads.
- Upload files.
- `im:message.group_msg` for group-history lookup when a user sends audio first and mentions the bot later.

Without `im:message.group_msg`, the bridge can still process media events that Feishu pushes directly, but it cannot fetch recent group history to recover the previous audio/file.

## Run

Start or restart the Feishu event subscriber for the configured lark-cli profile:

```bash
python start_ws.py restart --config config.toml --profile qiao-test
```

Then start the bridge:

```bash
python -m feishu_claudecode_qiao --config config.toml
```

On Windows, use one visible foreground window for the bridge while the event subscriber is checked and kept in the background:

```powershell
.\run_foreground.ps1 -Config config.realtest.toml -Profile qiao-test
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

Doctor:

```bash
python -m feishu_claudecode_qiao --config config.toml --doctor
```

## Chat Commands

| Command | Purpose |
|---|---|
| `/help` | Show command list |
| `/rules` | Show effective rules |
| `/context` | Show current session metadata |
| `/summary` | Show latest handoff summary |
| `/ask <question>` | Ask once without storing history |
| `/new` | Start a new Claude session |
| `/reset` | Reset current session |
| `/compact` | Force session rollover summary |
| `/workspace` | Show or update workspace when allowed |
| `/permission` | Show or update permission profile when allowed |

## Safety Model

Rules merge in this order:

```text
default -> chat -> member -> temporary
```

Permission profile mapping:

| Profile | Claude CLI mode | Intended use |
|---|---|---|
| `readonly` | `default` | Read-only conversations |
| `safe` | `default` | Normal group use |
| `dev` | `acceptEdits` | Trusted development group |
| `admin` | `bypassPermissions` | Highly trusted maintenance only |
| `stateless` | `default` | No session persistence |

The bridge also checks:

- Path whitelist before exposing local paths to Claude.
- Exact bot mention in group chats when `require_mention_in_group = true`.
- Blocked keywords.
- Risky intents such as delete, move, overwrite, shell, and sensitive path reads.
- Confirm or deny policy by risk category.

Personal chats use `bridge.personal_permission_profile`; trusted local deployments can set it to `admin` so direct 1:1 work runs with Claude `bypassPermissions`.

Group rule changes apply only to the group where the bot is mentioned. They are controlled by bot ownership, not Feishu group administrator status: if `bridge.bot_admins` is non-empty, only those users can change group rules; otherwise `bridge.bot_owner_id` is the only rule manager.

Production recommendation: default group rules to `safe` or `readonly`, restrict `allowed_paths`, keep `require_mention_in_group = true`, and configure `bot_owner_id`/`bot_admins` for rule management.

## Tested Real-World Flows

- Text group chat.
- Quoted group reply with sender mention.
- Receive reaction and reaction cleanup after processing.
- Local desktop file upload to group.
- Personal audio transcription.
- Group audio transcription after sending audio then mentioning the bot.
- Image recognition through Kimi Anthropic-compatible API.
- Restart without replaying old events.
- Missing Claude session auto-clear and retry.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Security

See [SECURITY.md](SECURITY.md). Never commit real Feishu secrets, Vision keys, `config.toml`, runtime data, or logs.
