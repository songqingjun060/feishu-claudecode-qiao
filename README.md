# Feishu-Claudecode-Qiao

## 中文说明

Feishu-Claudecode-Qiao 是一个本地运行的飞书机器人桥接工具，用来把飞书消息转交给 Claude Code CLI 处理，再把 Claude 的回复、生成文件或查询结果发回飞书。

它的定位不是把所有能力都塞进桥本身，而是让桥负责飞书通信、安全规则、文件收发和会话管理，让 Claude Code 负责真正的代码、文档、表格、PDF、压缩包和本地工具调用。

## 功能特性

- 支持飞书个人会话和群聊中的文本对话。
- 群聊回复会引用原消息并 @ 发送者。
- 收到消息后添加临时响应标记，处理完成后自动清理。
- 将 Claude 的 Markdown 回复转换成飞书交互卡片。
- 支持按会话配置工作目录、可访问路径、权限档位和会话模式。
- 支持 Claude 会话记录、上下文延续和自动压缩。
- 支持把 Claude Code 生成的本地文件上传回当前飞书会话。
- 支持下载飞书图片，并调用视觉模型分析。
- 支持下载飞书音频，并用 Whisper 转写。
- 支持“先发音频，再 @ 机器人”的群聊音频处理流程。
- 支持下载飞书普通文件，并把本地文件路径交给 Claude Code 处理。
- 支持审计日志、运行状态检查和 doctor 自检。

## 项目结构

```text
feishu_claudecode_qiao/
  bridge.py              主事件循环、飞书 API、Claude CLI 调用
  config.py              TOML 和环境变量配置
  security.py            路径白名单、敏感词、风险意图检查
  chat_rules.py          会话规则文件管理
  rule_engine.py         默认/会话/成员规则合并
  session_store.py       Claude 会话元数据和压缩计数
  commands.py            /help、/rules、/context、/workspace、/permission
  audit.py               JSONL 审计日志
  doctor.py              环境自检
  message_formatter.py   Markdown 转飞书卡片
  logger.py              滚动日志
tests/                   Pytest 回归测试
```

运行数据默认写入 `data_dir`：

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

`data/`、`data-test/`、`config.toml`、`config.realtest.toml`、日志和压缩包默认不提交到 Git。

## 安装

```bash
python -m pip install -e ".[dev]"
```

如需音频转写能力：

```bash
python -m pip install -e ".[voice]"
```

开发和测试环境推荐：

```bash
python -m pip install -e ".[dev,voice]"
python -m pytest -q
```

## 配置

复制示例配置：

```powershell
copy config.example.toml config.toml
```

编辑 `config.toml`：

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
personal_permission_profile = "admin"
bot_owner_id = ""
bot_admins = []

[security]
allowed_paths = []
blocked_keywords = []
```

也可以使用 `FEISHUCLAUDECODE_` 前缀的环境变量覆盖配置。

## 飞书应用权限

修改飞书应用权限后，需要重新发布应用。通常需要以下能力：

- 接收消息事件。
- 发送消息。
- 添加和删除消息表情回应。
- 回复消息。
- 读取消息资源，用于下载图片、音频和文件。
- 上传文件。
- `im:message.group_msg`，用于群聊中“先发音频/文件，再 @ 机器人”的历史消息查找。

如果缺少 `im:message.group_msg`，桥仍然可以处理飞书直接推送的媒体事件，但无法主动回查群里的上一条音频或文件。

## 群聊与个人权限

个人会话使用 `bridge.personal_permission_profile`。可信的本地部署可以设置为 `admin`，对应 Claude Code 的 `bypassPermissions`。

群聊建议保持：

```toml
require_mention_in_group = true
```

这样机器人只响应明确 @ 当前机器人的消息。匹配规则是精确匹配：飞书 mention ID 必须等于当前应用 ID，或 mention 展示名必须和 `bot_display_name` 完全一致。多个机器人在同一个群里时，务必正确设置 `bot_display_name`。

群规则只对当前群生效。规则管理不依赖飞书群管理员：

- 如果配置了 `bridge.bot_admins`，只有列表中的用户能改群规则。
- 如果没有配置 `bridge.bot_admins`，只有 `bridge.bot_owner_id` 能改群规则。

## 安全模型

规则合并顺序：

```text
default -> chat -> member -> temporary
```

权限档位：

| 档位 | Claude CLI 模式 | 适用场景 |
|---|---|---|
| `readonly` | `default` | 只读对话 |
| `safe` | `default` | 普通群聊 |
| `dev` | `acceptEdits` | 可信开发群 |
| `admin` | `bypassPermissions` | 高信任维护场景 |
| `stateless` | `default` | 不保留会话 |

桥还会检查：

- 本地路径是否在允许范围内。
- 群聊是否精确 @ 当前机器人。
- 是否命中阻断关键词。
- 是否存在删除、移动、覆盖、shell、敏感路径读取等高风险意图。
- 是否需要确认或拒绝。

`workspace` 和 `allowed_paths` 会写入发送给 Claude Code 的安全边界提示中，要求 Claude 只讨论和处理当前会话授权的路径；桥本身仍会在读取本地路径、缓存文件和上传文件时做硬性路径校验。

注意：`allowed_paths = []` 不是“允许全盘”。如需允许访问本地路径，请在规则或配置里明确放行。

## 文件处理

桥负责接收飞书文件、下载到本地、保存近期文件上下文，并把本地文件路径交给 Claude Code。

具体内容解析优先交给 Claude Code 和本机工具：

- PDF：Claude Code 可使用 `pypdf`、`pdfplumber` 等 Python 工具。
- Word：可使用 `python-docx`。
- Excel/CSV：可使用 `openpyxl`、`pandas`。
- PPT：可使用 `python-pptx`。
- 压缩包：可先列出内容，再按需解压分析。
- 视频：可使用 `ffprobe`、`ffmpeg` 提取元数据、关键帧、缩略图或音频。

桥本身不会把这些能力都内置成重型解析器，避免和 Claude Code 的工具能力重复。

## 启动

启动或重启飞书事件订阅：

```bash
python start_ws.py restart --config config.toml --profile qiao-test
```

启动桥服务：

```bash
python -m feishu_claudecode_qiao --config config.toml
```

Windows 推荐使用前台窗口运行，便于观察日志：

```powershell
.\run_foreground.ps1 -Config config.toml -Profile qiao-test
```

Windows 一键启动或重启：

```powershell
.\start_all.ps1
.\start_all.ps1 -Restart
.\start_all.ps1 -Restart -Foreground
```

查看状态：

```bash
python -m feishu_claudecode_qiao --config config.toml --status
```

停止：

```bash
python start_ws.py stop --config config.toml
python -m feishu_claudecode_qiao --config config.toml --stop
```

环境自检：

```bash
python -m feishu_claudecode_qiao --config config.toml --doctor
```

## 飞书命令

| 命令 | 作用 |
|---|---|
| `/help` | 显示命令列表 |
| `/rules` | 查看当前生效规则 |
| `/context` | 查看当前会话元数据 |
| `/summary` | 查看最近一次压缩摘要 |
| `/ask <问题>` | 单次提问，不写入长期上下文 |
| `/new` | 开启新的 Claude 会话 |
| `/reset` | 重置当前会话 |
| `/compact` | 强制压缩当前会话 |
| `/workspace` | 查看或修改工作目录 |
| `/permission` | 查看或修改权限档位 |

## 已验证流程

- 群聊文本对话。
- 群聊引用回复并 @ 发送者。
- 收到消息添加响应标记，完成后清理。
- 本地文件上传到飞书会话。
- 个人音频转写。
- 群聊中先发送音频，再 @ 机器人处理。
- 通过 Kimi Anthropic-compatible API 做图片识别。
- 重启后不重复处理旧事件。
- Claude 会话丢失时自动清理并重试。

## 故障排查

参见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 安全说明

参见 [SECURITY.md](SECURITY.md)。不要提交真实飞书密钥、视觉模型密钥、`config.toml`、`config.realtest.toml`、运行数据或日志。

---

## English Documentation

Feishu-Claudecode-Qiao is a local Feishu bot bridge for Claude Code CLI. It receives Feishu messages, applies per-chat rules and safety checks, calls Claude Code, and sends formatted replies, generated files, or query results back to Feishu.

The bridge is intentionally lightweight: it handles Feishu communication, safety rules, file transfer, and session state, while Claude Code handles code work, document analysis, spreadsheets, PDFs, archives, local tools, and project operations.

## Features

- Text chat with Claude Code in Feishu direct messages and group chats.
- Group replies quote the source message and mention the sender.
- Temporary reaction when a message is received, removed after processing.
- Markdown output converted to Feishu interactive cards.
- Per-chat workspace, allowed paths, permission profile, and session mode.
- Claude session store with context continuity and automatic compaction support.
- Upload local files generated by Claude Code back to the current Feishu chat.
- Download Feishu images and analyze them through a vision model.
- Download Feishu audio and transcribe it with Whisper.
- Group workflow for "send audio first, then mention the bot".
- Download Feishu files and pass local file paths to Claude Code.
- Audit logs, status checks, and doctor diagnostics.

## Project Structure

```text
feishu_claudecode_qiao/
  bridge.py              Main event loop, Feishu API calls, Claude CLI calls
  config.py              TOML and environment configuration
  security.py            Path whitelist, blocked keywords, risky intent checks
  chat_rules.py          Per-chat rule file management
  rule_engine.py         Default/chat/member rule merging
  session_store.py       Claude session metadata and compaction counters
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

`data/`, `data-test/`, `config.toml`, `config.realtest.toml`, logs, and release archives are intentionally ignored by Git.

## Install

```bash
python -m pip install -e ".[dev]"
```

Optional audio support:

```bash
python -m pip install -e ".[voice]"
```

Recommended development setup:

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
personal_permission_profile = "admin"
bot_owner_id = ""
bot_admins = []

[security]
allowed_paths = []
blocked_keywords = []
```

Environment variables with the `FEISHUCLAUDECODE_` prefix can override config values.

## Feishu App Permissions

Enable and publish the Feishu app after permission changes. Required capabilities usually include:

- Receive message events.
- Send messages.
- Add and delete message reactions.
- Reply to messages.
- Read message resources for image/audio/file downloads.
- Upload files.
- `im:message.group_msg` for group-history lookup when a user sends audio or a file first and mentions the bot later.

Without `im:message.group_msg`, the bridge can still process media events pushed directly by Feishu, but it cannot fetch recent group history to recover the previous audio or file.

## Direct Message And Group Permissions

Direct messages use `bridge.personal_permission_profile`. Trusted local deployments can set it to `admin`, which maps to Claude Code `bypassPermissions`.

For group chats, keep:

```toml
require_mention_in_group = true
```

With this setting, the bridge only handles messages that mention the current bot. Mention matching is exact: the Feishu mention ID must match the configured app ID, or the mention display name must exactly equal `bot_display_name`. Set `bot_display_name` carefully when multiple bots are installed in the same group.

Group rules apply only to the group where the bot is mentioned. Rule management does not depend on Feishu group administrator status:

- If `bridge.bot_admins` is non-empty, only those users can change group rules.
- Otherwise, `bridge.bot_owner_id` is the only rule manager.

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

- Whether a local path is allowed.
- Whether a group message exactly mentions the current bot.
- Blocked keywords.
- Risky intents such as delete, move, overwrite, shell, and sensitive path reads.
- Whether confirmation or denial is required.

`workspace` and `allowed_paths` are included in the security-boundary prompt sent to Claude Code, instructing Claude to only discuss and operate on paths authorized for the current chat. The bridge still enforces hard path checks when exposing local paths, caching files, or uploading files.

Note: `allowed_paths = []` does not mean "allow all drives". Add explicit paths in rules or config when local access is required.

## File Handling

The bridge receives Feishu files, downloads them locally, keeps recent file context, and passes local file paths to Claude Code.

Content parsing is delegated to Claude Code and local tools:

- PDF: `pypdf`, `pdfplumber`, or similar Python tools.
- Word: `python-docx`.
- Excel/CSV: `openpyxl`, `pandas`.
- PowerPoint: `python-pptx`.
- Archives: list contents first, then extract as needed.
- Video: `ffprobe` and `ffmpeg` for metadata, keyframes, thumbnails, or audio extraction.

The bridge does not embed heavy parsers for every file type, avoiding duplicated functionality with Claude Code.

## Run

Start or restart the Feishu event subscriber:

```bash
python start_ws.py restart --config config.toml --profile qiao-test
```

Start the bridge:

```bash
python -m feishu_claudecode_qiao --config config.toml
```

On Windows, use one visible foreground window:

```powershell
.\run_foreground.ps1 -Config config.toml -Profile qiao-test
```

One-command Windows start or restart:

```powershell
.\start_all.ps1
.\start_all.ps1 -Restart
.\start_all.ps1 -Restart -Foreground
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
| `/summary` | Show latest compaction summary |
| `/ask <question>` | Ask once without storing long-term context |
| `/new` | Start a new Claude session |
| `/reset` | Reset current session |
| `/compact` | Force session compaction |
| `/workspace` | Show or update workspace |
| `/permission` | Show or update permission profile |

## Tested Flows

- Text group chat.
- Quoted group reply with sender mention.
- Receive reaction and reaction cleanup after processing.
- Local desktop file upload to Feishu chat.
- Direct-message audio transcription.
- Group audio transcription after sending audio then mentioning the bot.
- Image recognition through Kimi Anthropic-compatible API.
- Restart without replaying old events.
- Missing Claude session auto-clear and retry.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Security

See [SECURITY.md](SECURITY.md). Never commit real Feishu secrets, Vision keys, `config.toml`, `config.realtest.toml`, runtime data, or logs.
