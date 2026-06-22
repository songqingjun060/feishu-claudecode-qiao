# Feishu-Claudecode-Qiao

本项目是一个本地运行的飞书机器人桥：接收飞书消息，交给 Claude Code CLI 或实验性常驻 runner 处理，再把文本回复、生成文件或查询结果发回飞书。

桥本身负责飞书通信、安全规则、文件收发、媒体上下文、会话记忆和运行审计；Claude Code 负责真正的代码、文档、表格、PDF、压缩包和本地工具处理。

## 主要能力

- 支持飞书个人会话和群聊；群聊默认要求明确 @ 当前机器人。
- 同一 chat 串行处理，避免同一对话内上下文错乱；不同 chat 可并行。
- 支持消息 reaction 作为临时处理中标记，并静默订阅 reaction created/deleted 事件降低日志噪声。
- 支持短文本合并窗口和较长媒体批处理窗口，降低简单问答等待，同时保留图片/文件/语音批处理体验。
- 支持图片、文件、语音下载；语音默认在桥启动时预加载 Whisper，第一条语音不再承担模型冷启动。
- 支持会话规则：工作目录、allowed_paths、权限档位、session_mode、每 chat 独立 soul。
- 支持长期记忆、会话翻页、`/memory`、`/rollover`、`/reset`、`/runtime` 等运行命令。
- 支持 `oneshot` 稳定 runner 和 `persistent` SDK-backed 实验加速 runner；persistent 失败会自动回退 oneshot。
- audit 日志包含 `message_id`、策略、耗时、runtime 复用和 startup 注入状态，便于按消息排查。

## 安装

```bash
python -m pip install -e ".[dev,voice]"
python -m pytest -q
```

如需实验性 Claude 常驻 runner：

```bash
python -m pip install -e ".[persistent]"
```

## 配置

复制示例配置：

```powershell
copy config.example.toml config.toml
```

核心配置示例：

```toml
[feishu]
app_id = "cli_xxxxx"
app_secret = "xxxxx"
domain = "https://open.feishu.cn"
gateway_backend = "current"
event_backend = "start_ws"

[claude]
command = "claude"
work_dir = "."
permission_mode = "safe"
runner = "oneshot"
worker_idle_ttl_seconds = 900
max_workers = 3
persistent_enabled_chats = []

[whisper]
model = "base"
load_policy = "preload"  # preload / lazy / per_call

[bridge]
data_dir = "./data"
log_level = "INFO"
require_mention_in_group = true
bot_display_name = "your-bot-display-name"
personal_permission_profile = "admin"
ws_profile = "qiao-test"
queue_notice_after_seconds = 8
media_batch_window_seconds = 10
text_coalesce_window_seconds = 2
message_coalesce_window_seconds = 10
fast_tasks_enabled = true
bot_owner_id = ""
bot_admins = []

[security]
allowed_paths = []
blocked_keywords = []
```

本地工具快速路径使用通用 `[[local_tools]]` 配置。桥只负责命中关键词/正则、执行本地命令、解析 stdout 和上传工具返回的附件路径；具体业务逻辑放在你自己的本地工具里，不需要提交到本项目。

```toml
[[local_tools]]
name = "sample_lookup"
enabled = true
keywords = ["查询", "lookup"]
match_patterns = ["\\b[A-Z]{2}\\d{4}\\b"]
command = ["python", "lookup.py", "--ids", "{matches}"]
cwd = "D:/your-local-tool"
timeout_seconds = 180
summary_fields = ["summary", "message", "text"]
attachment_path_fields = ["attachment_path", "file_path", "excelFilePath", "excel_path"]
context_label = "sample lookup result"
```

重要说明：

- `oneshot` 是稳定默认：每条消息调用一次 Claude CLI，保留 `session_id` 做上下文延续。
- `persistent` 是 SDK-backed 实验加速：按 chat 保留 worker，用 startup prompt hash 判断 soul、规则、长期记忆是否已注入；hash 未变化时不重复注入。
- `text_coalesce_window_seconds` 默认较短，用于普通文本连续发送合并。
- `message_coalesce_window_seconds` 默认较长，用于图片、文件、语音等媒体上下文批处理。
- `preload` 会让桥启动慢一些，但语音首条响应更稳；如希望启动更快，可改为 `lazy`。

## 运行

推荐用一键脚本启动或重启桥和对应 WebSocket 订阅：

```powershell
.\start_all.ps1 -Restart
```

后台启动：

```powershell
.\start_all.ps1 -Restart -Background
```

状态和停止：

```powershell
python -m feishu_claudecode_qiao --config config.toml --status
python -m feishu_claudecode_qiao --config config.toml --stop
python start_ws.py status --config config.toml --profile qiao-test
```

桥和 WebSocket 按同一 `config.toml + bridge.data_dir + bridge.ws_profile` 绑定。多机器人并行时，每个桥应使用独立的 `data_dir` 和 `ws_profile`。

## 常用命令

| 命令 | 作用 |
|---|---|
| `/help` | 查看命令 |
| `/rules` | 查看当前规则 |
| `/workspace set <path>` | 设置当前 chat 工作目录 |
| `/paths add <path>` | 增加允许访问路径 |
| `/permission set <readonly|safe|dev|admin>` | 设置权限档位 |
| `/soul` / `/soul set ...` | 查看或设置当前 chat 独立角色 |
| `/memory` / `/memory history` | 查看长期记忆 |
| `/memory refresh` | 立即压缩当前 Claude session 并刷新长期记忆 |
| `/memory clear` | 清空长期记忆，保留当前 session |
| `/rollover` | 总结当前 session，清空 session_id，带长期记忆开启新会话 |
| `/reset session` | 只清空当前 session_id |
| `/reset all` | 清空 session_id 和长期记忆 |
| `/runtime` | 查看 runner、worker、复用和 startup hash 状态 |

## 安全边界

默认规则偏保守：

- 群聊需要明确 @ 当前机器人。
- `allowed_paths = []` 不等于允许全盘访问。
- 桥会检查本地路径、敏感关键词和删除/移动/覆盖/shell 等风险意图。
- 规则中的 workspace、allowed_paths 和权限档位会写入发给 Claude Code 的安全边界提示。
- 即使本地 Claude CLI 使用高权限模式，桥仍会在读取、缓存和上传本地文件前做路径校验。

个人会话可通过 `bridge.personal_permission_profile` 设置最大权限；可信本地部署可设为 `admin`，对应 Claude Code `bypassPermissions`。

## 会话和记忆

每个飞书对话框会根据 `session_mode` 生成 session key：

- `shared_chat`：同一群或个人会话共享一条 Claude 上下文。
- `per_user`：群内按用户拆分上下文。
- `stateless`：不保留 Claude session。

长期记忆保存在 `data/sessions.json` 中，注入时受 `memory_policy.inject_max_chars` 控制。单次 Claude 慢响应只写 audit，不会自动设置下一轮 force rollover；只有显式规则、上下文真实超限、session 异常或用户命令才会翻页。

## 日志和排障

运行数据默认写入 `data_dir`：

```text
data/
  bridge.pid
  feishu_ws.pid
  sessions.json
  rules/
  logs/bridge.log
  logs/messages.log
  logs/audit.jsonl
  logs/feishu_ws.log
  logs/feishu_ws_events.jsonl
  images/
  attachments/
```

重点日志：

- `logs/bridge.log`：服务、token、Claude、媒体、WebSocket 管理。
- `logs/messages.log`：收发消息流程。
- `logs/audit.jsonl`：`message_id`、合并、会话策略、耗时、安全和回复事件。

排查慢响应时优先看 `message_timing.stage_ms`：

- `received_to_coalesced`：合并窗口等待。
- `received_to_rules_resolved`：事件解析或规则读取。
- `rules_resolved_to_prompt_built`：媒体上下文、近期文件/语音、记忆或 prompt 构建。
- `prompt_built_to_claude_completed`：Claude CLI/SDK、session 恢复、模型推理或工具调用。
- `claude_completed_to_reply_sent` / `claude_completed_to_file_sent`：飞书发送或文件上传。

更多部署和排障说明见：

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- [docs/TESTED_FLOWS.md](docs/TESTED_FLOWS.md)

## 不要提交的内容

`.gitignore` 默认排除：

- `data/`、`data-test/`
- `config.toml`、`config.realtest.toml`
- `.env`
- 日志、附件、图片、缓存和构建产物

不要公开分享真实配置和日志；它们可能包含聊天内容、本地路径和敏感配置线索。
