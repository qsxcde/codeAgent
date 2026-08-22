## Context

见 proposal.md — Why。复用资产:
- `SessionManager.continue_recent()` 已实现(manager.py,CLI `--continue` 在用)——`recent` 快捷零新逻辑;
- 补全浮层已支持 picker 语义(`spec.picker=True`,provider/model/effort/login 先例)与固定窗口滚动——交互式选择器复用该通道;
- `manager.list()` 返回 `SessionRef`(含派生标题/时间/id),候选数据现成;
- 订阅跟随:切换会话(`manager.switch`)对订阅方无感,选择器确认后无需重建视图。

## Goals / Non-Goals

**Goals:**
- `/sessions` 无参 → 交互式选择器(历史会话候选,↑↓ 选择,Enter 切换)。
- `/sessions recent` → 快速恢复最近会话(复用 `continue_recent`)。
- `list` / `new` / `<id>` 既有语义零破坏。

**Non-Goals:**
- 不新增 `/resume` 命令(用户已定:增强 `/sessions` 替代)。
- 不改 `continue_recent` 语义(CLI/TUI 共享,行为稳定)。
- 不做启动时自动恢复最近会话(探索期未选,保持启动恒新建的既有行为)。

## Decisions

### D1: 复用 picker 浮层通道,而非独立的 `/resume` 命令

`sessions` 注册为 `picker=True`(commands.py),无参 `/sessions` 即"命令名确认 → 进入内联选择器"(既有 `_on_suggestion_confirm` 的 picker 分支直接复用),无需新增命令类型或视图分支。

- **理由**:provider/model/effort/login 已走同一通道——命令名候选(浮层)→ 确认 → 值候选(浮层)→ 确认生效;sessions 完全同构,改动最小、交互一致;
- 候选值 = `manager.list()` 的会话展示串(标题优先,`id` 兜底),标记当前会话;确认后 `manager.switch(id)`。
- 备选(独立 `/resume` + 专用状态机)否决:重复实现浮层交互,与既有 picker 通道不一致。

### D2: `recent` 为 `/sessions` 参数分支,复用 continue_recent

`_cmd_sessions` 的 action 分派增加 `recent` 分支 → `manager.continue_recent()`;无 store(防御性,`list()` 为空)时 `continue_recent` 已回退新建,反馈语义与 spec 一致。

- **理由**:命令面收敛(一个命令三态),`continue_recent` 是现成纯调用;
- `recent` 与无参选择器的差异:`recent` = 确定性(最近一个),无参 = 交互(用户选)。

### D3: 无会话空态与选择器候选生成

无会话时 `_picker_candidates("sessions")` 返回空列表 → 浮层不弹(既有行为),`_cmd_sessions` 无参分支在候选为空时显示「(暂无会话)」提示(与现有 `/sessions list` 空态一致)。

- **理由**:避免空浮层;提示语义与既有 `list` 空态统一。

## Risks / Trade-offs

- [选择器候选仅展示标题,多会话标题相似难区分] → 候选串含 `id` 后缀(如 `标题 (id前8位)`),可区分;
- [切换会中止运行中会话(既有 `_halt_current`)] → 与 `/sessions <id>` 现状一致,不新增风险;
- [`recent` 语义 = 最近创建(按时间升序取末),非"最近活动"] → 与 CLI `--continue` 完全一致,共享语义,不在此变更扩大范围。

## Migration Plan

无数据迁移。命令语义纯增量(`recent` / 无参选择器为新增分支),既有 `list/new/<id>` 行为不变;无回滚需求。

## Open Questions

无(探索阶段已收敛:增强 `/sessions` 三态,复用 picker 通道与 `continue_recent`)。
