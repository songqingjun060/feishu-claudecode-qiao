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
- 支持 Claude 会话记录、上下文延续、会话翻页和自动压缩。
- 支持每个飞书对话框独立保存长期记忆，并在新 Claude 会话里受控注入。
- 支持把 Claude Code 生成的本地文件上传回当前飞书会话。
- 支持下载飞书图片，并把本地图片路径交给 Claude Code 处理。
- 支持连续图片上下文：单独发送的图片先缓存，不逐张触发 Claude；随后发送“读取刚才图片”一类文字时，会一次性带入最近图片路径。
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
  session_store.py       Claude 会话元数据、压缩计数和长期记忆
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
load_policy = "lazy"  # preload / lazy / per_call

[bridge]
data_dir = "./data"
log_level = "INFO"
max_upload_mb = 20
require_mention_in_group = true
bot_display_name = "your-bot-display-name"
ws_profile = "qiao-test"
ws_watchdog_interval_seconds = 30
ws_max_restart_failures = 3
console_message_log = true
console_claude_stream = true
queue_notice_after_seconds = 8
media_batch_window_seconds = 10
progress_cards = false
fast_tasks_enabled = true
personal_permission_profile = "admin"
bot_owner_id = ""
bot_admins = []

[security]
allowed_paths = []
blocked_keywords = []
```

也可以使用 `FEISHUCLAUDECODE_` 前缀的环境变量覆盖配置。

Claude 调用入口由 `[claude].runner` 控制：

| 值 | 行为 | 状态 |
|---|---|---|
| `oneshot` | 每条消息调用一次 `claude --print --resume`，处理完退出 | 当前默认和稳定模式 |
| `persistent` | 每个会话维护常驻 Claude worker | 预留实验模式 |
| `tmux` | 通过 tmux/终端会话复用 Claude 运行态 | 预留实验模式 |

消息队列和媒体批处理的基础配置：

| 配置 | 默认值 | 说明 |
|---|---:|---|
| `bridge.queue_notice_after_seconds` | `8` | 排队超过该秒数才提示一次，避免无限回复“忙/排队中” |
| `bridge.media_batch_window_seconds` | `10` | 连续图片、文件和补充说明的归并窗口 |
| `bridge.progress_cards` | `false` | 是否启用飞书进度卡片；未启用时继续使用文本和日志 |
| `bridge.fast_tasks_enabled` | `true` | 是否启用固定业务快速路径；命中 BI 物流码等明确任务时先由桥直接调用本地工具，失败再交给 Claude |

语音模型加载策略由 `[whisper].load_policy` 控制：

| 值 | 行为 | 适用场景 |
|---|---|---|
| `preload` | 桥启动时加载 Whisper，并在进程内常驻 | 希望第一条语音也快，接受启动变慢和提前占用内存 |
| `lazy` | 第一次语音时加载，之后常驻复用 | 默认推荐，启动快，后续语音快 |
| `per_call` | 每条语音临时加载，用完释放 | 语音很少、希望平时不常驻占内存 |

会话翻页和长期记忆的默认策略来自会话规则 `context_policy` 和 `memory_policy`。当前全局 `config.toml` 只读取固定的 `[feishu]`、`[claude]`、`[whisper]`、`[bridge]`、`[security]` 配置表；如需按群或成员调整策略，请通过会话规则文件修改，避免在全局配置里加入加载器尚未消费的表。

默认策略偏向稳定延续：普通对话不会因为达到旧的 35 轮就频繁新开 Claude 会话，只有达到更高阈值、上下文真实超限或 session 异常时才翻页。

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

## 会话、翻页和长期记忆

每个飞书对话框会根据 `session_mode` 生成独立的 Claude session key。默认 `shared_chat` 表示同一个群或个人会话共享一条 Claude 上下文；`per_user` 表示同一个群里按用户拆分；`stateless` 表示不保留 Claude 会话。

会话翻页指主动结束当前 Claude session，并在保留摘要或长期记忆的前提下开启新的 Claude session。它用于处理上下文过长、session 丢失或用户主动要求重新整理上下文的场景，不等同于删除长期记忆。

长期记忆保存在 `data/sessions.json` 对应的会话记录里，通常包含当前对话框里的稳定事实、用户偏好、项目路径、权限设置和未完成事项。注入时会受 `memory_policy.inject_max_chars` 控制，避免把过长历史塞回新会话。

常用命令区别：

| 命令 | 作用 |
|---|---|
| `/rollover` | 总结当前 Claude session，清空当前 `session_id`，保留长期记忆并开启后续新会话 |
| `/reset` | 只重置当前 `session_id`，保留长期记忆 |
| `/reset session` | 与 `/reset` 相同，用于更明确地表达只重置 session |
| `/reset all` | 清空当前对话的 `session_id` 和长期记忆 |
| `/memory` | 查看当前对话框的长期记忆 |
| `/memory history` | 查看最近保存过的记忆摘要 |
| `/memory refresh` | 立即压缩当前 Claude 会话并刷新长期记忆 |
| `/memory clear` | 只清空长期记忆，保留当前 `session_id` |
| `/compact` | 强制压缩当前 Claude 会话上下文 |

每个飞书对话框还可以有独立的 `soul`，用于定义这个 chat 里的机器人角色、语气、业务背景和输出风格。它会在当前 chat 的常驻运行体启动时注入一次，后续普通消息只增量发送。

| 命令 | 作用 |
|---|---|
| `/soul` | 查看当前对话框的角色设定 |
| `/soul set name <名称>` | 设置角色名称 |
| `/soul set role <角色>` | 设置当前对话框里的职责定位 |
| `/soul set tone <语气>` | 设置回复语气 |
| `/soul set business <业务背景>` | 设置业务背景 |
| `/soul set style <输出风格>` | 设置输出格式偏好 |
| `/soul reset` | 重置当前对话框的角色设定 |
| `/runtime` | 查看当前 Claude runner 和常驻 worker 状态 |

示例：

```text
/soul set role 当前群的仓库和物流协作助手
/soul set tone 简洁、稳一点，优先给可执行结论
/memory refresh
/runtime
```

如需关闭长期记忆，请在对应会话规则里设置：

```json
{
  "memory_policy": {
    "enabled": false
  }
}
```

## 文件处理

桥负责接收飞书文件、下载到本地、保存近期文件上下文，并把本地文件路径交给 Claude Code。

连续发送的裸图片会先进入当前对话框的近期文件上下文，不会每张图片都单独调用 Claude 或单独回复。随后发送明确任务文本，例如“读取刚才图片进行物流码查询”，桥会把最近缓存的多张图片路径一起注入给 Claude Code 处理。带文字的富文本图片消息会在同一次请求中把全部图片路径交给 Claude Code。

桥会为同一聊天、同一发送人在短时间内连续发送的图片或文件生成媒体批次上下文。个人会话默认可合并；群聊必须是同一发送人并且后续消息明确 @ 当前机器人。不同发送人的附件不会自动合并，避免把别人的文件错当成你的任务上下文。

具体内容解析优先交给 Claude Code 和本机工具：

- PDF：Claude Code 可使用 `pypdf`、`pdfplumber` 等 Python 工具。
- Word：可使用 `python-docx`。
- Excel/CSV：可使用 `openpyxl`、`pandas`。
- PPT：可使用 `python-pptx`。
- 压缩包：可先列出内容，再按需解压分析。
- 视频：可使用 `ffprobe`、`ffmpeg` 提取元数据、关键帧、缩略图或音频。

桥本身不会把这些能力都内置成重型解析器，避免和 Claude Code 的工具能力重复。

## 固定业务快速路径

开启 `bridge.fast_tasks_enabled = true` 后，桥会先识别少量确定性强的业务任务。当前已接入 BI 物流码查询：

- 文本明确包含“BI/物流码/查询”等意图。
- 能提取到来源单号、WMS 配货单号或物流码。
- 直接调用本机 `C:\Users\tanks\BI-wuliumachaxun` 下的查询工具。
- 查询结果包含 Excel 时，桥会直接上传到当前飞书会话。
- 如果工具失败、输入不明确或置信度不足，会继续走 Claude Code，不会硬拦截。

快速路径只处理固定业务任务，不改变图片、PDF、表格、压缩包等通用文件由 Claude Code 和本机工具读取的主方案。

## 启动

Windows 默认使用前台窗口运行，便于观察日志。推荐通过一键脚本启动或重启，它会按同一个配置绑定桥和 WebSocket 订阅：

```powershell
Set-Location -LiteralPath D:\feishu-claudecode-qiao
.\start_all.ps1 -Restart
```

如果明确需要隐藏后台运行：

```powershell
.\start_all.ps1 -Restart -Background
```

桥和 WebSocket 订阅按同一个 `config.toml`、`bridge.data_dir`、`bridge.ws_profile` 绑定。桥停止时会停止对应 WebSocket；桥重启时会重启对应 WebSocket；桥运行中发现对应 WebSocket 死掉会先自动拉起，连续失败达到 `ws_max_restart_failures` 后才停止桥，避免多机器人环境互相影响。

前台值守窗口默认会同时显示消息收发日志和 Claude 流式输出：收到消息时能看到会话类型、发送者、内容摘要；调用 Claude 时会显示“Claude 思考中...”并实时打印文本增量；发送完成后会显示回复或文件上传结果。若明确需要安静后台日志，可把 `console_message_log` 或 `console_claude_stream` 设为 `false`。

如果只想手动管理 WebSocket，可使用：

```powershell
python start_ws.py restart --config config.toml --profile qiao-test
```

查看状态：

```bash
python -m feishu_claudecode_qiao --config config.toml --status
```

停止：

```bash
.\start_all.ps1 -Stop
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
| `/memory` | 查看当前对话框的长期记忆 |
| `/memory history` | 查看最近保存过的记忆摘要 |
| `/memory clear` | 清空当前对话框的长期记忆 |
| `/ask <问题>` | 单次提问，不写入长期上下文 |
| `/new` | 开启新的 Claude 会话 |
| `/rollover` | 手动会话翻页，保留长期记忆 |
| `/reset` | 重置当前 Claude session，保留长期记忆 |
| `/reset session` | 明确只重置当前 Claude session |
| `/reset all` | 重置当前 Claude session 并清空长期记忆 |
| `/compact` | 强制压缩当前会话 |
| `/workspace` | 查看或修改工作目录 |
| `/permission` | 查看或修改权限档位 |

## Claude 500 和异常重试

Claude 偶发 `api error: 500` 或 `internal server error` 时，桥会优先把它当成临时错误处理：等待后使用同一个 session 重试一次。只有持续失败时才向用户返回简短提示，不会因为一次 500 就强制翻页。

如果 Claude 返回 session 缺失，桥会清空已保存的 `session_id` 并重试一次。如果返回上下文长度超限，桥会执行翻页流程，携带长期记忆开启新 session 后再重试。

## 飞书 SDK 迁移策略

当前默认链路继续使用已经跑通的 HTTP 调用和 `lark-cli` 事件订阅。后续接入官方飞书 SDK 时，需要同时保留两层边界：

- `FeishuGateway`：封装发送消息、回复消息、上传文件、下载文件、添加表情回应和删除表情回应。
- `FeishuEventSubscriber`：封装事件订阅的 `start`、`stop`、`restart`、`status` 生命周期。

官方 SDK 后端不能绕开 `FeishuEventSubscriber` 直接启动事件流。无论底层是 `lark-cli` 还是 `lark-oapi` WebSocket，都必须继续遵守 `config.toml + bridge.data_dir + bridge.ws_profile` 的一对一绑定，保证桥停止时事件订阅停止、桥重启时事件订阅重启、订阅连续恢复失败时桥退出。

SDK 后端应作为实验性实现逐步接入，默认不改变生产行为。只有网关测试稳定、现有 HTTP 后端保持兼容，并且可以按配置显式切换后，才切换到 `lark-oapi` 或其他官方 SDK 实现。

当前可配置的后端选择：

```toml
[feishu]
gateway_backend = "current"   # 当前 HTTP API 后端
event_backend = "start_ws"    # 当前 lark-cli/start_ws.py 事件订阅后端
```

`lark_oapi` 和 `lark_oapi_ws` 已保留为实验后端名称，但当前版本只提供占位、前台 warning 和 doctor 提示，尚未实现生产可用的官方 SDK 后端。后续官方 SDK 后端也必须复用同一套前台值守日志和一对一生命周期管理，不能另起一个脱离桥管理的事件进程。

## 已验证流程

- 群聊文本对话。
- 群聊引用回复并 @ 发送者。
- 收到消息添加响应标记，完成后清理。
- 本地文件上传到飞书会话。
- 个人音频转写。
- 群聊中先发送音频，再 @ 机器人处理。
- 图片下载后交给 Claude Code 使用本机工具处理。
- 重启后不重复处理旧事件。
- Claude 会话丢失时自动清理并重试。

## 故障排查

参见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 安全说明

参见 [SECURITY.md](SECURITY.md)。不要提交真实飞书密钥、`config.toml`、`config.realtest.toml`、运行数据或日志。
## Claude 常驻模式

默认模式仍然是 `oneshot`：每条消息调用一次 `claude --print`，处理完退出，稳定性最高。

如果希望降低个人会话或高频群聊的冷启动耗时，可以启用 `persistent`：

```toml
[claude]
runner = "persistent"
worker_idle_ttl_seconds = 900
max_workers = 3
persistent_enabled_chats = []
```

`persistent` 使用可选依赖 `claude-agent-sdk` 为每个对话保留一个 Claude worker。缺少 SDK、worker 崩溃或常驻调用失败时，桥会自动回退到 `oneshot`，不会因为常驻模式不可用导致消息完全无响应。

安装可选依赖：

```powershell
python -m pip install -e ".[persistent]"
```

`persistent_enabled_chats` 留空表示所有对话都可尝试常驻；如果只想先给个人对话或某几个群启用，可以填写对应的 `chat_id` 或 `session_key`。常驻模式能减少 CLI 冷启动和恢复 session 的开销，但如果某个 Claude 会话本身已经积累了很大的上下文，仍然需要配合会话翻页、长期记忆压缩和快速任务直通来控制 token。

## 上下文调度和轻量会话

桥会在每条消息进入 Claude 前判断会话策略：

- `work`：文件、图片、表格、BI、路径、代码和复杂任务，继续使用当前工作 session。
- `light`：当当前工作 session 已经很重，而用户只发短文本聊天或测速时，不再 resume 旧 session，避免简单消息被大上下文拖慢。
- `fresh`：明确 `/new` 或规则要求新会话时，不带旧 session，但仍可注入桥内长期记忆。
- `stateless`：完全不记录本轮。

默认 `auto` 会自动判断。慢响应会被记录到 audit，并标记当前 chat 下一轮优先整理/翻页。相关审计字段包括 `context_decision`、`strategy`、`prompt_chars`、`memory_context_chars`、`resumed` 和 `claude_ms`。
