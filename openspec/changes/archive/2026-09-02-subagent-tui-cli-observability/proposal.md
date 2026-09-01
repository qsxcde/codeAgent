## Why

V5-06 已经把子 Agent 的排队、启动、进度和唯一终态以有界的父级事件发布出来，但当前 TUI 只归约普通消息与工具事件，headless CLI 也会静默丢弃这些事件。用户因此无法判断委派是否正在运行、卡在确认、失败、超时或已返回结果；现在需要在不泄漏子 Agent 完整 transcript 的前提下把这条观测链路接到展示层。

## What Changes

- 在 TUI 中增加独立的委派块，按 `delegation_id` 原位更新排队、运行、等待确认、取消和终态信息。
- 默认以紧凑摘要展示子任务 profile、阶段、耗时、结果摘要和稳定诊断；不把子 Agent 渲染成普通工具调用，也不复制完整子消息或工具输出。
- 让 TUI 正确处理父子 run/session 关联、乱序和迟到事件：子事件只能更新对应委派块，不得覆盖父运行状态、正文或其它委派。
- 在状态栏提供有界的委派聚合信息，并保持既有固定槽位、窄终端降级和长会话渲染性能约束。
- 在 headless CLI 的一次性和交互循环中输出稳定的委派状态/终态行，保留 reason code、耗时和清理不确定诊断，并过滤 prompt、完整 transcript 和无界 payload。
- 增加离线模型、组件、事件乱序、多个委派、父级取消、迟到事件、终态幂等和性能回归测试。

## Capabilities

### New Capabilities

- `subagent-observability`: 定义父级 TUI/CLI 对 Subagent 事件和有限结果的展示、过滤、关联及终态语义。

### Modified Capabilities

- `tui`: 增加 Subagent 委派块、状态栏聚合、父子事件隔离及相应的离线渲染与性能要求。

## Impact

- 影响 `src/codeagent/app/tui/state/`、`src/codeagent/app/tui/presentation/`、TUI 事件桥接/渲染协调器和 `src/codeagent/app/headless.py`。
- 新增展示层内部状态对象和组件，不改变 `AgentEvent`、`SubagentResult` 或 `delegate` 的公共输入契约。
- 需要更新 TUI 与 headless 的行为测试、快照/样式断言、性能 fixture 和 v0.5 迭代记录；不引入新依赖，不改变 JSONL 持久化格式。
