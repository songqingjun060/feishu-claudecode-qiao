# 部署指南

本文用于干净的本地或团队部署。

## 1. 准备 Python 和 Claude CLI

需要：

- Python 3.10 或更高版本。
- 本机可以直接执行 `claude` 命令。
- 已创建并配置好的飞书应用凭证。

安装完整开发和音频依赖：

```bash
python -m pip install -e ".[dev,voice]"
```

如果不需要音频转写，可以只安装：

```bash
python -m pip install -e ".[dev]"
```

## 2. 配置飞书应用

创建或复用一个飞书应用，并配置：

- 接收消息事件订阅。
- 发送消息权限。
- 回复消息权限。
- 消息表情回应权限。
- 消息资源读取和下载权限。
- 文件上传权限。
- 如果使用“先发音频，再 @ 机器人”的群聊流程，需要 `im:message.group_msg`。

修改飞书应用权限后，需要重新发布应用，并重启桥。

## 3. 配置桥

复制示例配置：

```bash
copy config.example.toml config.toml
```

编辑 `config.toml`：

```toml
[feishu]
app_id = "cli_xxxxx"
app_secret = "xxxxx"
gateway_backend = "current"
event_backend = "start_ws"

[claude]
command = "claude"
work_dir = "D:/your/workspace"
permission_mode = "safe"

[whisper]
model = "base"
load_policy = "preload"

[bridge]
data_dir = "./data"
require_mention_in_group = true
bot_display_name = "your-bot-display-name"
console_message_log = true
console_claude_stream = true
personal_permission_profile = "admin"
bot_owner_id = "your-feishu-open-id"
bot_admins = []

[security]
allowed_paths = ["D:/your/workspace"]
```

同一个群里有多个机器人时，必须把 `bot_display_name` 设置成当前机器人的飞书显示名称。群消息只有在明确 @ 当前机器人，或 mention 展示名与 `bot_display_name` 完全匹配时才会处理。

个人会话使用 `personal_permission_profile`。群规则只对当前群生效，并由机器人所有者控制：如果 `bot_admins` 为空，只有 `bot_owner_id` 可以修改群规则；如果设置了 `bot_admins`，则只有列表里的用户可以修改群规则。

语音模型加载策略可以按使用方式选择：

- `preload`：桥启动时加载并常驻，默认推荐，第一条语音更快，但启动更慢。
- `lazy`：第一次语音时加载并常驻，启动更快但第一条语音会慢。
- `per_call`：每条语音临时加载，不常驻占用内存，但每条语音都会慢。

可信维护群可以在桥运行过一次后创建 `data/rules/<chat_id>.json`：

```json
{
  "workspace": "D:/your/workspace",
  "allowed_paths": ["D:/your/workspace"],
  "permission_profile": "safe",
  "session_mode": "shared_chat"
}
```

## 4. 媒体和文件处理

图片、普通文件和视频会先由桥下载到本地，再把本地路径交给 Claude Code。具体内容分析由 Claude Code 和本机工具完成，桥不需要额外配置单独的图片分析接口。

连续发送的裸图片会先进入当前会话的近期文件上下文，不会逐张触发 Claude。随后发送“读取刚才图片”一类任务文本时，桥会把最近缓存的图片路径一次性交给 Claude Code。

## 5. 自检

```bash
python -m feishu_claudecode_qiao --config config.toml --doctor
python -m pytest -q
```

`doctor` 中 `feishu_gateway_backend` 和 `feishu_event_backend` 应显示当前稳定后端。如果显示 `lark_oapi` 或 `lark_oapi_ws selected but not implemented`，说明配置已经切到尚未实现的实验后端。

## 6. 启动

Windows 上可直接双击 `start_qiao.cmd`。默认是前台窗口，方便观察日志。

命令行启动：

```powershell
Set-Location -LiteralPath D:\feishu-claudecode-qiao
.\run_foreground.ps1 -Restart
```

如果明确需要隐藏后台运行：

```powershell
.\run_foreground.ps1 -Restart -Background
```

桥和 WebSocket 订阅会按同一个 `config.toml`、`bridge.data_dir`、`bridge.ws_profile` 绑定。桥停止时会停止对应 WebSocket；桥重启时会重启对应 WebSocket；桥运行中发现对应 WebSocket 死掉会先自动拉起，连续恢复失败达到 `ws_max_restart_failures` 后桥才退出。

默认前台窗口会显示消息收发、Claude 流式输出、回复预览和发送结果。若是纯后台部署，可以关闭前台镜像：

```toml
[bridge]
console_message_log = false
console_claude_stream = false
```

也可以手动管理 WebSocket：

```bash
python start_ws.py restart --config config.toml --profile qiao-test
python start_ws.py status --config config.toml --profile qiao-test
```

单独前台启动桥：

```bash
python -m feishu_claudecode_qiao --config config.toml
```

Windows 前台窗口脚本：

```powershell
.\run_foreground.ps1 -Config config.realtest.toml -Profile qiao-test
```

查看状态：

```bash
python -m feishu_claudecode_qiao --config config.toml --status
```

停止：

```bash
python start_ws.py stop --config config.toml --profile qiao-test
python -m feishu_claudecode_qiao --config config.toml --stop
```

## 7. 冒烟测试

在飞书群里测试：

1. 发送 `@your-bot-display-name 测试连接`。
2. 确认机器人收到后添加临时响应标记，并在回复后清理。
3. 确认群聊回复引用原消息，并 @ 发送者。
4. 连续发送多张图片，再发送明确任务文本，确认 Claude Code 收到本地图片路径。
5. 发送一条短音频，再 @ 机器人或发送 `@your-bot-display-name 读上一条消息`。
6. 要求机器人上传一个已授权路径下的小文件。

## 8. 升级

停止桥，替换源码。如果依赖有变化，重新安装，再启动：

```bash
python -m feishu_claudecode_qiao --config config.toml --stop
python -m pip install -e ".[dev,voice]"
python -m feishu_claudecode_qiao --config config.toml
```

通常可以保留 `data/` 里的运行数据，但不要把真实配置、日志、聊天内容或密钥提交到 Git。
## Claude 常驻模式部署

默认部署不需要安装额外依赖，`[claude].runner = "oneshot"` 会继续使用当前的一次性 Claude CLI 调用方式，也是稳定默认 fallback。

如需启用常驻模式，先安装可选依赖：

```powershell
python -m pip install -e ".[persistent]"
```

然后在配置中启用：

```toml
[claude]
runner = "persistent"
worker_idle_ttl_seconds = 900
max_workers = 3
persistent_enabled_chats = []
```

说明：

- `persistent` 是 SDK-backed 实验加速模式，会按飞书对话保留 Claude worker，减少 CLI 冷启动和恢复 session 的耗时。
- `persistent_enabled_chats = []` 表示所有对话都可尝试常驻；也可以填写指定 `chat_id` 或 `session_key` 先小范围启用。
- 如果缺少 `claude-agent-sdk`、worker 启动失败或常驻调用异常，桥会自动回退 `oneshot`，不会导致整桥无响应。
- 常驻 worker 会用 startup prompt hash 判断角色、规则和长期记忆启动注入是否已经加载；hash 未变化时会复用，减少重复注入。
- 常驻模式不能替代长期记忆压缩。某个 Claude 会话上下文过大时，仍然需要使用会话翻页、摘要压缩或快速任务直通来降低 token。
- 部署后可以在飞书发送 `/runtime` 查看当前 runner 和 worker 复用状态；发送 `/memory refresh` 可以手动压缩当前对话并刷新长期记忆。
- 每个群或个人会话可以用 `/soul`、`/soul set role ...`、`/soul set tone ...` 设置独立角色，不会影响其他对话。

