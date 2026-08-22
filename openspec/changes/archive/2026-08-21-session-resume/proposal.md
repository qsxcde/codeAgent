## Why

TUI 会话恢复体验差:启动恒新建会话(`manager.create()`),历史会话需手动记 id 再 `/sessions <id>` 切换;"恢复最近会话"能力(`continue_recent`)在 CLI 已存在但 TUI 无入口。对齐主流 agent(Claude Code 的 `/resume`)体验,增强 `/sessions` 命令:快速恢复最近会话 + 交互式选择器恢复,无需新增独立命令。

## What Changes

- `/sessions` 命令增强为三态交互:
  - `/sessions`(无参)→ **交互式恢复**:固定窗口浮层列出历史会话(标题 / id / 时间),↑↓ 选择、Enter 切换;
  - `/sessions recent` → **快速恢复最近会话**(复用 `continue_recent`,无会话时新建);
  - `/sessions new` / `/sessions <id>` → 既有语义不变。
- 命令注册为 picker 语义(`picker=True`),复用既有补全浮层(命令名候选 + 值候选)与确认分派。
- 候选来源 `manager.list()`(会话列表含派生标题);选择确认走 `manager.switch(id)`(订阅跟随既有,切换无感)。
- 无会话时浮层显示空态提示;无 store(防御性)时报错提示。

## Capabilities

### New Capabilities

- `tui/session-resume`:会话快速恢复与交互式选择恢复能力——`/sessions` 无参交互选择、`recent` 快捷恢复、既有 list/new/id 语义保持。

### Modified Capabilities

- `tui`: `/sessions` 命令需求从"列出并可切换会话"扩展为"列列表/新建/按 id 切换/**recent 恢复最近**/**无参交互式选择器**"。
- `sessions`: 会话管理需求补充——"恢复最近会话"作为 `SessionManager` 可被 TUI 消费的既有能力显式进入会话管理契约(CLI 已用,TUI 复用)。

## Impact

- `src/codeagent/app/tui/commands.py`:`sessions` 注册为 picker + `recent` 语义(参数解析)。
- `src/codeagent/app/tui/view.py`:`_picker_candidates` 为 sessions 提供会话候选;`_on_suggestion_confirm` 值确认分派 sessions 切换;`_cmd_sessions` 增加 `recent` 分支与无参走选择器。
- `src/codeagent/session/manager.py`:`continue_recent()` 已存在(CLI 在用),本变更仅使其可经 TUI 到达——无改动或仅文档化。
- 测试:命令分派(picker/recent/空态)、候选列表(含标题)、选择确认切换、无会话/无 store 边界。
