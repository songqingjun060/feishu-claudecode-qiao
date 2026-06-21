# 故障排查

本文记录常见部署问题、排查命令和已经验证过的处理方式。

## 群聊里机器人不回复

先检查：

- 飞书应用是否收到了 `im.message.receive_v1` 事件。
- `require_mention_in_group = true` 时，群消息是否明确 @ 了当前机器人。
- 如果 mention ID 没有匹配应用 ID，`bot_display_name` 是否和飞书里显示的机器人名称完全一致。
- `bridge.pid` 指向的 Python 进程是否仍在运行。
- `data/logs/feishu_ws_events.jsonl` 是否持续增长。
- `data/logs/bridge.log` 是否有 token 或发送消息错误。
- `python start_ws.py status --config config.toml` 是否显示当前飞书应用对应的 `lark-cli` 订阅进程正在运行。

常用命令：

```bash
python -m feishu_claudecode_qiao --config config.toml --status
python -m feishu_claudecode_qiao --config config.toml --doctor
python start_ws.py status --config config.toml --profile qiao-test
```

多机器人并行时，每个桥必须使用独立的 `bridge.data_dir` 和对应的 `bridge.ws_profile`。`feishu_ws.meta.json` 会记录当前 WebSocket 属于哪个 config/profile；如果状态检查显示 metadata 不匹配，说明当前桥不应该接管那个 WebSocket，请用对应配置执行 `.\start_all.ps1 -Restart`。

如果 @ 了别的机器人但本桥也回复，请升级到包含精确 mention 匹配的版本。旧版本可能只检查 `mentioned_type = bot`，没有校验具体机器人。

如果 @ 当前机器人仍不回复，请确认配置：

```toml
[bridge]
require_mention_in_group = true
bot_display_name = "your-bot-display-name"
```

## 前台窗口看不出是否在处理

默认前台运行会显示消息收发日志和 Claude 流式输出。如果窗口只看到服务启动信息，看不到 `📩` 收到消息、`Claude 思考中...` 或 `✅ 回复已发送`，请检查：

- `bridge.console_message_log` 是否为 `true`。
- `bridge.console_claude_stream` 是否为 `true`。
- 是否使用了 `.\start_all.ps1 -Restart` 前台启动，而不是 `-Background`。
- `data/logs/messages.log` 是否仍在写入。如果文件有内容但前台没有，通常是前台镜像开关被关闭。

后台部署可以关闭这两个开关，日志仍会写入 `bridge.log` 和 `messages.log`。

## 重启后回复旧消息

桥启动时会从事件文件当前末尾开始读取。如果仍然回复旧消息，请确认运行进程是最新版本并重启：

```bash
python -m feishu_claudecode_qiao --config config.toml --stop
python -m feishu_claudecode_qiao --config config.toml
```

不要手动删除真实日志或 `data-test` 来解决这个问题；优先通过状态命令和进程重启确认读取偏移。

## 群聊回复没有引用或没有 @ 发送者

群聊回复应走飞书回复接口：

```text
POST /open-apis/im/v1/messages/{message_id}/reply
```

文本回复会在开头加飞书 at-mention。卡片回复会在卡片顶部加 mention。文件回复会引用原消息，但文件载荷本身不能嵌入文本。

如果缺少引用或 mention，请确认当前版本使用 `_send_event_reply` 路径，并确认飞书应用具备回复消息权限。

## 图片处理失败

图片由桥下载到本地，再把本地路径交给 Claude Code。失败时检查：

- 图片资源是否成功下载。
- 保存路径是否位于当前会话的 `workspace` 或 `allowed_paths` 边界内。
- Claude CLI 当前权限档位是否允许读取该路径。
- `data/logs/bridge.log` 是否有资源下载、路径校验或 Claude 调用错误。

如果用户连续发送多张单独图片，桥会先缓存图片，不会逐张回复。需要再发送一条明确任务文本，例如“读取刚才图片进行物流码查询”。如果后续文本没有带入图片，请检查：

- 图片是否在 30 分钟近期上下文窗口内。
- 图片消息和任务文本是否在同一个飞书对话框。
- 群聊里是否已经正确 @ 当前机器人。
- 群聊里图片和后续任务文本是否来自同一发送人。
- `bridge.media_batch_window_seconds` 是否被设置得过短。

图片内容本身仍由 Claude Code 和本机工具读取。桥只负责下载、保存路径、合并上下文，不会默认启用额外的 Vision 中间层。

## 私聊音频正常但群聊音频不正常

检查：

- 飞书应用是否能收到群聊音频事件。
- 应用是否有下载消息资源的权限。
- 是否安装了音频依赖：

```bash
python -m pip install -e ".[voice]"
```

如果使用“先发音频，再 @ 机器人”的群聊流程，还需要权限：

```text
im:message.group_msg
```

缺少这个权限时，桥仍可处理飞书直接推送到桥的媒体事件，但无法主动回查群里的上一条音频或文件。

语音转写默认使用 `whisper.load_policy = "preload"`：桥启动时加载并缓存 Whisper 模型，第一条语音不再承担模型冷启动。转写时默认指定中文识别，减少繁体或语言漂移。如果启动变慢但后续语音稳定，这是正常现象。

可选策略：

- `preload`：桥启动时加载并常驻，默认推荐，第一条语音更快。
- `lazy`：第一次语音时加载并常驻，启动更快但第一条语音会慢。
- `per_call`：每条语音临时加载，用完释放，适合很少使用语音且希望平时不占内存的场景。

## 文件上传失败

桥只会在以下条件全部满足时上传本地文件：

- 用户消息明确要求发送或上传本地文件。
- 本地文件路径或桌面文件名片段可以被解析。
- 路径被当前群或成员规则允许。
- 文件存在且没有超过 `max_upload_mb`。
- 飞书应用有文件上传和发送消息权限。

桥不会自动复制用户机器上的运行文件；必须先解析并校验路径。

## BI 物流码快速路径没有命中

快速路径只在确定性较高时启用。请检查：

- `bridge.fast_tasks_enabled` 是否为 `true`。
- 文本里是否明确包含“BI”“物流码”“查询”等词。
- 是否能从消息里提取来源单号、WMS 配货单号或物流码。
- `bridge.bi_logistics_tool_dir` 指向的目录是否正确；默认是 `D:\BI-wuliumachaxun`，这份工具支持 `api.enabled` 接口直查。
- 工具目录下是否存在 `query-logistics-codes.js` 或 `BI-wuliumachaxun.exe`。
- BI 工具本身是否能在 PowerShell 中独立执行。

快速路径失败时桥会直接返回失败原因，不再静默等待 Claude Code。排查耗时请看 `data/logs/audit.jsonl` 中的 `fast_task_started`、`fast_task_completed`、`fast_task_failed`。

## Claude 提示无法读取本地文件

这里有两层权限：

- 桥的路径规则决定某个路径能否交给 Claude。
- Claude CLI 权限模式决定 Claude 能否读取或编辑文件。

可信本地测试可以把 `permission_profile = "admin"` 映射到 Claude CLI 的 `bypassPermissions`。生产环境建议使用 `safe` 或 `readonly`。

## 冷启动体感明显

如果每次对话都像新会话，先检查当前会话是否使用了 `stateless`，或是否被频繁 `/reset all` 清空长期记忆。

默认策略会尽量延续当前 Claude session，并在 session 异常或上下文超限时携带长期记忆开启新 session。长期记忆保存在 `data/sessions.json` 的会话记录中，重启桥后仍可加载。

当前稳定 runner 是 `claude.runner = "oneshot"`：桥会保留 `session_id`，但每条消息仍会新启动一次 Claude CLI。`persistent` 是基于可选 `claude-agent-sdk` 的实验加速模式，缺少 SDK、worker 启动失败或常驻调用异常时会回退 `oneshot`；启用前应先确认测试和回退策略。

如果要判断慢在哪里，优先查看 `data/logs/audit.jsonl` 中的 `message_timing`：

- `received_to_rules_resolved` 偏大：事件解析或规则读取慢。
- `prompt_built_to_claude_completed` 偏大：Claude CLI 启动、session 恢复、模型推理或工具调用慢。
- `claude_completed_to_file_sent` 偏大：本地文件上传到飞书或发送消息慢。
- `media_start_to_media_cached` 偏大：图片、语音或文件下载/转写慢。

`context_decision`、`message_timing`、`message_coalesced` 等审计记录会带上 `message_id`，方便和飞书原消息对齐。单次 Claude 慢响应只记录耗时，不会自动标记下一轮翻页；只有显式会话策略、上下文真实超限、session 异常或 `/rollover` 命令才会触发翻页。

可用命令：

```text
/context
/memory
/memory history
/memory refresh
/runtime
```

如果不希望注入长期记忆，请在对应会话规则中设置 `memory_policy.enabled = false`，而不是删除真实数据文件。

如果当前对话框需要固定角色、语气或业务背景，可以用 `/soul` 查看，并用 `/soul set role ...`、`/soul set tone ...` 等命令调整。`soul` 是按 chat 保存的，不会影响其他群或个人会话。

## 会话频繁翻页

会话翻页会清空当前 `session_id` 并让后续请求进入新的 Claude session。它通常只应发生在达到策略阈值、上下文真实超限、session 缺失或用户手动执行 `/rollover` 时。

排查方向：

- 查看 `/context` 中的消息计数、最近翻页时间和当前 session 状态。
- 检查会话规则里的 `context_policy` 是否把阈值设置得过低。
- 检查日志里是否反复出现上下文超限或 session 缺失。
- 确认是否有人在群里执行 `/rollover`、`/reset` 或 `/reset all`。

命令区别：

| 命令 | 处理方式 |
|---|---|
| `/rollover` | 手动翻页，保留长期记忆 |
| `/reset` | 只重置当前 `session_id`，保留长期记忆 |
| `/reset session` | 与 `/reset` 相同，语义更明确 |
| `/reset all` | 重置 session 并清空长期记忆 |
| `/memory refresh` | 立即压缩当前 Claude session，并刷新长期记忆 |
| `/memory clear` | 只清空长期记忆，不主动重置当前 session |

## Claude session 缺失

如果 Claude 返回 `No conversation found with session ID`，桥会清空保存的旧 `session_id` 并重试一次。若反复出现，可在飞书里执行：

```text
/reset session
```

旧命令也可以使用：

```text
/reset
```

只有确认要同时删除长期记忆时，才使用：

```text
/reset all
```

不建议在桥运行时手工编辑 `data/sessions.json`。如果必须编辑，请先停止桥。

## Claude 500 或临时服务错误

如果 Claude 返回 `api error: 500` 或 `internal server error`，桥会优先按临时错误处理：等待后用同一个 session 重试一次。一次 500 不会触发强制翻页，也不会清空长期记忆。

如果重试后仍失败，桥会向用户返回简短提示。排查时查看：

```text
data/logs/bridge.log
data/logs/messages.log
```

如果同时出现上下文长度超限，桥会执行翻页流程，带上长期记忆开启新 session 后重试一次。

## 飞书 SDK 迁移相关问题

当前稳定链路仍是 HTTP 调用加 `lark-cli` 事件订阅。后续迁移官方飞书 SDK 时，应同时通过 `FeishuGateway` 和 `FeishuEventSubscriber` 两个边界并行接入，保持默认后端不变。

排查 SDK 实验后端时，优先确认：

- 默认 HTTP 后端是否仍可工作。
- 发送、回复、上传、下载、表情回应能力是否都有网关测试覆盖。
- SDK WebSocket 是否实现 `FeishuEventSubscriber.start/stop/restart/status`，并继续遵守 `config.toml + data_dir + ws_profile` 的一对一生命周期绑定。
- 是否只有显式配置后才切换到 SDK 后端。
- `doctor` 中 `feishu_gateway_backend` 和 `feishu_event_backend` 是否仍显示当前稳定后端；如果显示 `lark_oapi` 或 `lark_oapi_ws selected but not implemented`，说明配置已经切到尚未实现的实验后端。
- 实验 SDK 后端启用失败时，前台窗口是否打印“官方 lark-oapi 后端尚未实现”的 warning。
- 失败时是否能快速切回当前 HTTP 和 `lark-cli` 链路。

## 需要查看的日志

```text
data/logs/bridge.log       服务、token、API、Claude、媒体处理
data/logs/messages.log     收发消息流程
data/logs/audit.jsonl      安全决策、message_id、会话策略、合并和回复事件
```

不要公开分享日志；日志可能包含聊天内容、本地路径和敏感配置线索。
## Claude 常驻模式没有生效

先看前台窗口或 `bridge.log`，启动时应该能看到类似：

```text
Claude runner: persistent
```

如果仍然显示 `oneshot`，请检查当前启动命令使用的配置文件是不是你修改过的那个，例如：

```powershell
.\start_all.ps1 -Restart -Foreground -Config config.realtest.toml
```

如果配置为 `persistent` 但实际响应仍然像 one-shot，常见原因：

- 没有安装可选依赖：`python -m pip install -e ".[persistent]"`
- `persistent_enabled_chats` 只允许了某些 `chat_id` 或 `session_key`，当前对话不在列表里。
- 常驻 worker 启动或调用失败，桥自动回退到 `oneshot`。这种情况下桥仍会回复，但日志里会出现 SDK 或 worker 相关错误。
- startup prompt hash 没有变化时，常驻 worker 会复用已注入的角色、规则和长期记忆启动上下文；这属于正常加速行为，不代表规则没有加载。
- 当前 Claude session 上下文过大。常驻能减少进程冷启动，但不能让 6 万 token 的上下文瞬间变小，需要配合 `/rollover`、长期记忆压缩或固定任务快速路径。

可以在飞书里发送 `/runtime` 查看当前 runner、active worker 数量，以及当前 chat 是否已经复用同一个 worker。

建议先只给个人会话或一个测试群开启常驻，确认稳定后再扩大范围。
