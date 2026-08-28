## Why

当前 Runtime 主要通过 `current_task`、`active_run_id` 和若干异常分支隐式表达运行状态，导致模型请求、工具执行、确认等待、持久化和最终收尾之间缺少统一契约。阶段 1 需要先固定生命周期、错误分类和事件终态，作为取消、TUI、恢复和后续扩展的共同基础。

## What Changes

- 建立可观察且受约束的运行阶段：idle、starting、model_wait、tool_running、awaiting_confirmation、continuing、completed、failed、cancelled、finalizing。
- 为一次运行引入结构化状态、结果和失败信息，统一 `run_id`、`session_id`、阶段、可重试性、副作用状态和清理确定性。
- 统一 core Agent 事件与 session 运行事件的边界，保证事件具备稳定关联字段和唯一终态。
- 将模型、工具、确认、递归超限、持久化和压缩失败归入稳定错误分类，保留面向用户的诊断文本。
- 保证 SessionRuntime 创建 Agent 时不丢失工具执行模式、后置钩子和停止策略等配置。

## Capabilities

### New Capabilities

无。本变更收敛现有 core/session 运行契约。

### Modified Capabilities

- `core`: 修改“事件契约”，补充运行关联字段、终态唯一性和结构化失败语义。
- `sessions`: 修改“SessionManager 生命周期管理”，使会话切换、释放和关闭遵守运行终止与收尾边界；新增会话运行终态要求。

## Impact

- 影响 `src/codeagent/core/events.py`、`src/codeagent/core/errors.py`、`src/codeagent/core/agent.py`、`src/codeagent/session/runtime/controller.py` 和 `src/codeagent/session/session.py`。
- 可能新增 session runtime 状态/错误模型，并调整事件消费者读取的 metadata 字段。
- TUI、CLI 和测试需要使用结构化终态，而不是通过错误文本或布尔字段推断运行状态。
- 不引入新的编排框架；不把持久化、安全策略或 UI 逻辑下沉到 core。
