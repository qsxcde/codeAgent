## Why

V4-28 已经提供生命周期 Hook，但 Hook 失败目前只能以裸异常元组记录，无法稳定说明哪个 Hook 在哪个生命周期阶段失败；事件快照复制失败还可能反向破坏 Agent 主流程。现在补齐异常隔离，才能让观察扩展真正保持只读、可诊断且不影响运行收尾。

## What Changes

- 增加 provider-neutral 的结构化 Hook 诊断，包含 Hook 身份、作用域、阶段、事件类型、运行关联、失败阶段和异常类型/消息。
- 隔离同步 Hook、异步 Hook 以及生命周期快照构造失败；继续执行其它 Hook，不改变 Agent 的成功、失败、取消、持久化和清理语义。
- 在 core Agent 和 AgentSession 暴露内存诊断查询；保留现有裸错误属性，避免破坏已有调用方。
- 让 session 汇总 core 与 session 两侧的 Hook 诊断；诊断不写入用户会话历史或 JSONL 持久化。
- 为失败和取消收尾补充回归测试、架构说明和 v0.4 状态记录。

## Capabilities

### New Capabilities

### Modified Capabilities

- `lifecycle-hooks`: 增加 Hook 异常诊断、快照失败隔离和取消收尾保证。

## Impact

- 影响 `core/contracts/hooks.py`、`core/agent.py`、session 事件/运行桥接及公开导出。
- 新增只读内存诊断 API，不新增依赖，不改变已有 AgentEvent/EventBus 和会话存储格式。
- 观察 Hook 的异常消息会进入运行期诊断对象；实现不得将凭据或用户历史写入持久化。
