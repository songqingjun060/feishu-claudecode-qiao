# 对话记忆、会话翻页和飞书 SDK 评估改造计划

> **给执行代理的说明：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，并按任务逐项执行。任务使用复选框（`- [ ]`）跟踪进度。

**目标：** 降低飞书对话里 Claude Code 的冷启动体感，让每个对话框的长期记忆更稳定，并为后续低风险接入官方飞书 SDK 预留接口。

**架构：** 先保留当前已经跑通的桥和 `lark-cli` 事件链路，只调整会话生命周期策略。再增加一个很小的飞书网关边界，让未来 SDK 迁移可以逐步替换，而不是一次性重写。

**技术栈：** Python 3.10+、pytest、本地 Claude Code CLI、Feishu/Lark CLI，后续可选 `lark-oapi`。

---

## 改造策略

本次工作分成两个发布阶段。

第一阶段关注用户体感稳定：
- 降低自动会话翻页频率。
- 只有上下文或 session 真实异常时才强制翻页。
- session 断开后注入更稳定的对话长期记忆。
- 增加清晰命令：`/rollover`、`/reset session`、`/reset all`、`/memory`。

第二阶段为飞书 SDK 迁移做准备：
- 在现有发送、上传、下载、表情反应能力外包一层 `FeishuGateway`。
- 在事件订阅侧增加 `FeishuEventSubscriber`，统一 `start`、`stop`、`restart`、`status` 生命周期。
- 当前 HTTP 和 `lark-cli` 实现继续作为默认方案。
- 只有网关测试稳定后，再增加实验性的 `lark-oapi` 后端。
- 先增加显式后端选择配置：`feishu.gateway_backend` 和 `feishu.event_backend`，默认仍为当前稳定链路。

## 涉及文件

- 修改：`feishu_claudecode_qiao/rule_engine.py`
  - 调整默认 `context_policy`。
  - 只有确实需要时再增加显式 `rollover_policy` 或 `memory_policy` 默认值。
- 修改：`feishu_claudecode_qiao/session_store.py`
  - 增加按策略判断的会话翻页辅助逻辑。
  - 只重置 session 时保留长期记忆。
- 修改：`feishu_claudecode_qiao/bridge.py`
  - 只在达到阈值或检测到上下文/session 异常时触发翻页。
  - 增加 `/rollover`、`/reset session`、`/reset all`。
  - 优化 Claude 500 和 session 缺失时的重试流程。
- 修改：`feishu_claudecode_qiao/commands.py`
  - 注册新命令。
- 修改：`config.example.toml`
  - 说明更稳妥的上下文和记忆默认策略。
- 修改：`README.md`
  - 增加会话、翻页和长期记忆的中文说明。
- 修改：`docs/TROUBLESHOOTING.md`
  - 增加冷启动、翻页、Claude 500 处理说明。
- 新建：`feishu_claudecode_qiao/feishu_gateway.py`
  - 定义飞书网关协议，并包装当前实现。
- 新建或修改测试：
  - `tests/test_session_store.py`
  - `tests/test_bridge_rollover.py`
  - `tests/test_bridge_commands.py`
  - `tests/test_feishu_gateway.py`

---

## 任务 1：放宽默认会话翻页策略

**文件：**
- 修改：`feishu_claudecode_qiao/rule_engine.py`
- 测试：`tests/test_session_store.py`

- [ ] **步骤 1：为新的默认阈值写失败测试**

增加断言：默认策略在 35 轮时不触发翻页，但达到新的硬阈值时才触发。

```python
def test_default_rollover_is_not_triggered_at_old_35_turn_limit():
    from feishu_claudecode_qiao.rule_engine import DEFAULT_RULE
    from feishu_claudecode_qiao.session_store import SessionMeta, calculate_rollover_score

    meta = SessionMeta(session_key="chat:c1")
    meta.message_count = 35

    score = calculate_rollover_score(meta, DEFAULT_RULE["context_policy"])

    assert score < DEFAULT_RULE["context_policy"]["score_threshold"]
```

- [ ] **步骤 2：运行测试并确认失败**

运行：

```powershell
python -m pytest tests/test_session_store.py -q
```

实施前预期：新增测试失败，因为当前 `hard_message_limit` 还是 35。

- [ ] **步骤 3：更新默认值**

设置为：

```python
"context_policy": {
    "mode": "auto_rollover",
    "score_threshold": 100,
    "soft_message_limit": 80,
    "hard_message_limit": 120,
    "ttl_hours": 168,
    "min_messages_between_rollovers": 30,
    "rollover_cooldown_hours": 12,
    "carry_summary": True,
    "context_error_only": False,
}
```

- [ ] **步骤 4：运行聚焦测试**

运行：

```powershell
python -m pytest tests/test_session_store.py tests/test_bridge_rollover.py -q
```

预期：全部通过。

---

## 任务 2：增加手动翻页和更清晰的重置命令

**文件：**
- 修改：`feishu_claudecode_qiao/commands.py`
- 修改：`feishu_claudecode_qiao/bridge.py`
- 测试：`tests/test_bridge_commands.py`

- [ ] **步骤 1：增加命令解析测试**

增加测试：

```python
def test_parse_rollover_command():
    from feishu_claudecode_qiao.commands import parse_command
    cmd = parse_command("/rollover")
    assert cmd.name == "rollover"
    assert cmd.is_command is True


def test_parse_reset_session_command():
    from feishu_claudecode_qiao.commands import parse_command
    cmd = parse_command("/reset session")
    assert cmd.name == "reset"
    assert cmd.args == "session"
```

- [ ] **步骤 2：运行失败测试**

运行：

```powershell
python -m pytest tests/test_bridge_commands.py -q
```

- [ ] **步骤 3：实现命令行为**

预期行为：
- `/rollover`：总结当前 Claude session，清空当前 `session_id`，保留长期记忆。
- `/reset` 和 `/reset session`：只清空当前 `session_id`，保留长期记忆。
- `/reset all`：清空当前对话的 session 和长期记忆。
- `/memory clear`：只清空长期记忆，保留当前 `session_id`。

- [ ] **步骤 4：运行聚焦测试**

运行：

```powershell
python -m pytest tests/test_bridge_commands.py tests/test_bridge_rollover.py -q
```

预期：全部通过。

---

## 任务 3：只在真实上下文/session 异常时触发翻页

**文件：**
- 修改：`feishu_claudecode_qiao/bridge.py`
- 测试：`tests/test_bridge_rollover.py`

- [ ] **步骤 1：增加异常触发翻页测试**

测试场景：
- Claude 回复 session 缺失：清空 session 并重试一次。
- Claude 回复上下文长度超限：总结后开新 session 重试。
- Claude 500：先重试一次或两次，除非连续失败，否则不强制翻页。

- [ ] **步骤 2：实现错误分类辅助函数**

增加小函数：

```python
def _is_context_limit_reply(self, reply: str) -> bool:
    text = reply.lower()
    return "context" in text and ("too long" in text or "length" in text or "exceeded" in text)


def _is_transient_claude_error(self, reply: str) -> bool:
    text = reply.lower()
    return "api error: 500" in text or "internal server error" in text
```

- [ ] **步骤 3：实现重试策略**

策略：
- session 缺失：清空 `session_id`，重试一次。
- 上下文超限：强制执行 `/rollover` 行为，携带长期记忆用新 session 重试一次。
- 500：等待 3 秒，用同一个 session 重试一次；如果仍然 500，返回简短的用户提示。

- [ ] **步骤 4：运行聚焦测试**

运行：

```powershell
python -m pytest tests/test_bridge_rollover.py -q
```

预期：全部通过。

---

## 任务 4：优化每个对话框的长期记忆结构和注入

**文件：**
- 修改：`feishu_claudecode_qiao/session_store.py`
- 修改：`feishu_claudecode_qiao/bridge.py`
- 测试：`tests/test_session_store.py`、`tests/test_bridge_rollover.py`

- [ ] **步骤 1：增加记忆字段测试**

长期记忆应保留：
- 当前对话框里的角色和人设。
- 用户偏好。
- 当前项目或任务。
- 重要路径和权限设置。
- 最近未完成事项。

- [ ] **步骤 2：更新记忆更新提示词**

提示词应要求 Claude 保留稳定事实、删除过期细节，并受 `inject_max_chars` 控制。

- [ ] **步骤 3：提升命令输出清晰度**

`/memory` 应显示版本、更新时间和前 1000 个字符。

- [ ] **步骤 4：运行测试**

运行：

```powershell
python -m pytest tests/test_session_store.py tests/test_bridge_rollover.py tests/test_bridge_commands.py -q
```

预期：全部通过。

---

## 任务 5：增加 FeishuGateway 和事件订阅边界，但暂不切换后端

**文件：**
- 新建：`feishu_claudecode_qiao/feishu_gateway.py`
- 修改：`feishu_claudecode_qiao/bridge.py`
- 修改：`start_ws.py`
- 测试：`tests/test_feishu_gateway.py`

- [ ] **步骤 1：定义网关协议**

创建方法：

```python
class FeishuGateway:
    def send_message(self, chat_id: str, content: str, msg_type: str = "text") -> dict: ...
    def reply_message(self, message_id: str, content: str, msg_type: str = "text") -> dict: ...
    def upload_file(self, path: str) -> str: ...
    def download_file(self, message_id: str, file_key: str, target_path: str) -> str: ...
    def add_reaction(self, message_id: str, reaction: str) -> None: ...
    def delete_reaction(self, message_id: str, reaction: str) -> None: ...
```

同时定义事件订阅生命周期协议：

```python
class FeishuEventSubscriber:
    def start(self, *, force: bool = False) -> bool: ...
    def stop(self) -> bool: ...
    def restart(self, *, force: bool = False) -> bool: ...
    def status(self) -> bool: ...
```

- [ ] **步骤 2：包装当前实现**

把现有桥里的 HTTP 调用挪到 `CurrentFeishuGateway` 后面。

把当前 `lark-cli`/`start_ws.py` 事件订阅包装到 `StartWsEventSubscriber` 后面。后续官方 SDK WebSocket 后端必须实现同一协议，不能绕过桥和 WebSocket 的一对一生命周期绑定。

- [ ] **步骤 3：保持行为不变**

桥仍然使用当前配置、`lark-cli` 事件文件和当前 token 流程。
事件订阅仍然按 `config.toml + bridge.data_dir + bridge.ws_profile` 绑定：桥停则订阅停，桥重启则订阅重启，订阅连续恢复失败则桥退出。

- [ ] **步骤 5：增加显式后端选择，但不启用 SDK**

默认值：

```toml
[feishu]
gateway_backend = "current"
event_backend = "start_ws"
```

保留实验名称 `lark_oapi` 和 `lark_oapi_ws`，但创建时明确抛出 `NotImplementedError`，并由 doctor 给出警告，避免误以为官方 SDK 后端已经可用。

- [ ] **步骤 4：运行全量测试**

运行：

```powershell
python -m pytest -q
```

预期：全部通过。

---

## 任务 6：更新文档和发布包

**文件：**
- 修改：`README.md`
- 修改：`docs/TROUBLESHOOTING.md`
- 修改：`config.example.toml`
- 如果需要发布包，同步修改干净复用包。

- [ ] **步骤 1：说明改动影响**

增加中文说明：
- 为什么对话不再频繁自动翻页。
- `/rollover`、`/reset session`、`/reset all`、`/memory clear` 的区别。
- 长期记忆存储在哪里。
- 如何关闭长期记忆。

- [ ] **步骤 2：更新配置示例**

如果全局配置加载器尚未读取单独的 `[context_policy]` 表，则只在 `config.example.toml` 里增加注释示例，避免破坏现有加载行为。示例内容：

```toml
[context_policy]
soft_message_limit = 80
hard_message_limit = 120
ttl_hours = 168
min_messages_between_rollovers = 30
rollover_cooldown_hours = 12

[memory_policy]
enabled = true
inject_max_chars = 4000
```

- [ ] **步骤 3：运行测试**

运行：

```powershell
python -m pytest -q
```

- [ ] **步骤 4：重建干净 ZIP**

只有测试通过后，才同步到 `D:\feishu-claudecode-qiao-clean-package` 并重建 `D:\feishu-claudecode-qiao-clean-package.zip`。

---

## 改动期间的影响

- 替换代码前应先停止当前桥。
- 代码替换期间，飞书消息可能仍会进入 WebSocket 事件日志，但桥重启前不会处理。
- `sessions.json` 保持兼容，旧 session 条目应能正常加载。
- 已经清空过 `session_id` 的对话可能还会新开一次 Claude session，但长期记忆会保留。
- 不应提交真实的 `config.realtest.toml`、日志、运行数据或密钥。
- 第二阶段 SDK 工作默认不改变生产行为，只有显式启用后才切换。
- SDK 事件订阅后端必须复用 `FeishuEventSubscriber` 生命周期，不允许另起一个脱离桥管理的 WebSocket 常驻进程。

## 开源项目对比备注

- 轻量 Lark/Feishu 桥通常强调快速部署和直接 CLI 转发。
- 多 IM skill 通常强调覆盖更多聊天平台。
- Slack 桥常强调运行中代理的连续性、打断和恢复。
- OpenClaw/Nexu 类项目更偏桌面网关和广义自动化。

本项目应该重点优化：
- 每个对话框的规则和权限档位。
- 本地优先的飞书群工作流。
- 让 Claude Code CLI 负责真正的代码、文档、表格、PDF、压缩包和本地工具调用。
- 稳定的文件、图片、语音上下文交接。
- Windows 前台可见运行和 WebSocket 守护。
- 桥和 WebSocket 订阅的一对一生命周期绑定。
- 每个对话框独立的长期记忆和受控注入。
