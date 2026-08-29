## Why

`src/codeagent/core` 已经承担了 Agent 编排、受控工具执行和上下文准备，但工具运行时仍直接识别 `Args`、`invoke`、`ainvoke` 等历史形态，且执行器、清理逻辑和 ReAct 循环超过仓库规定的文件/函数规模。需要收紧 core 的端口边界并完成职责拆分，避免核心层继续绑定具体工具实现约定。

## What Changes

- **BREAKING** 将 core 的工具执行契约收敛为 `AgentTool.execute(...)`，删除 core 对 `Args`、`invoke`、`ainvoke`、`invoke_async` 和 `args_schema` 的运行时兼容探测。
- 在 `tools/` 或 `app/composition/` 增加具体工具到 `AgentTool` 的显式适配，并由组合根挂载适配后的真实工具入口。
- 拆分 `core/execution.py` 的执行状态、调用、结果归一化和清理职责，使生产文件和函数满足规模要求。
- 拆分 `core/loop.py` 的单轮模型请求、工具批次和运行生命周期职责，保持并发、顺序、取消、超时、steer 和 follow-up 语义不变。
- 收紧 `core/ports.py`、`model_request.py` 和工具调用模块的类型边界，继续保持 core 不依赖 `ai`、`tools`、`session` 或配置实现。
- 保留当前 `TransformContext` 上下文转换兼容路径；本变更只移除旧工具执行协议兼容，不改变上下文预算、消息格式、事件语义和持久化格式。
- 增加严格 AgentTool 契约、适配器装配、取消/超时清理和禁止旧协议分支的回归测试，并修正测试分层。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `core`: 工具执行必须通过严格的 `AgentTool` 端口；运行时职责拆分后继续提供 ReAct、事件、控制和受控清理语义。
- `tools`: 内建工具和 MCP 工具通过显式适配器提供 core 所需的统一工具执行入口，具体工具 schema/执行实现不得由 core 反向识别。

## Impact

- 影响 `src/codeagent/core/ports.py`、`execution.py`、`loop.py`、`tool_result.py`、`model_request.py` 及其新拆分模块。
- 影响 `src/codeagent/tools/` 的工具适配和 `src/codeagent/app/composition/` 的工具装配。
- 影响 `tests/core/`、`tests/contracts/`、`tests/tools/` 和架构/规模检查。
- 可能影响直接向 `run_agent_loop` 或 `AgentLoopConfig` 传入旧式 `Args/invoke` 工具的内部调用方；这些调用方必须迁移到 `AgentTool` 适配器。
- 不新增运行时依赖，不改变 CLI/TUI 入口、事件字段、会话 JSONL、消息父子关系或已完成的上下文预算语义。
