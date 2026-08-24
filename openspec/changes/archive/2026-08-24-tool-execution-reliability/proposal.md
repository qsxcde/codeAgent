## Why

当前 Agent 的工具执行链已经可用，但仍有三个会影响长任务稳定性的缺口：流式工具参数解析失败时可能被静默降级为空对象，Agent 层超时取消可能只停止等待而未停止底层同步工具，模型和 MCP 端口热切换也缺少统一的资源释放生命周期。这些问题会导致工具行为不可解释、后台进程继续运行、HTTP 客户端或 MCP 线程累积，直接影响代码修改任务的安全性与可恢复性。

现在修复这些问题，是在增加任务级验证、多智能体或更多外部 Skill 之前稳定基础执行层的必要条件。

## What Changes

- 统一流式与非流式模型响应的工具参数解析，保留原始参数与解析错误，不再把非法 JSON 静默转换为空对象并执行。
- 将参数解析错误以结构化工具结果回传模型，使模型可以重新生成合法参数；既有 schema 校验错误继续作为工具错误回填。
- 增加受控的工具执行运行时：支持工具并发上限、超时状态、取消状态和执行清理结果。
- 统一 Agent 层工具超时与 bash/MCP 工具自身超时的语义，避免外层超时后底层同步任务继续无状态运行。
- 强化 bash 和 MCP 的取消路径：bash 继续终止进程树，MCP 调用在超时或取消时主动结束对应调用；无法强制抢占的同步工具必须明确报告降级语义。
- 增加模型客户端、MCP server 和工具集合的显式关闭接口；provider/model/login 热切换和 TUI 退出时释放旧资源，`atexit` 仅作为兜底。
- 扩展工具执行事件的 metadata，使订阅方可以区分参数错误、超时、取消、拒绝和清理完成状态，同时保持既有事件类型兼容。
- 增加参数错误、超时、取消、并发上限、热切换资源释放和 MCP 清理的离线回归测试。

本变更不包含任务级“修改后自动测试与修复”Supervisor、仓库索引、Git checkpoint/undo、记忆、多智能体、Web/HTTP 或新的 Skill 能力；这些属于后续独立变更。

## Capabilities

### New Capabilities

无。本变更完善已有核心执行契约，不引入独立用户能力域。

### Modified Capabilities

- `core`:工具调用参数解析失败、工具执行状态、超时/取消事件 metadata 和并发调度语义。
- `tools`:bash 工具的取消/进程清理状态，以及原子工具执行的受控超时语义。
- `mcp`:MCP 工具调用的主动取消、超时清理和 server 生命周期释放语义。

## Impact

- 主要代码：`src/codeagent/core/loop.py`、`src/codeagent/core/ports.py`、`src/codeagent/core/events.py`、`src/codeagent/app/container.py`、`src/codeagent/session/session.py`、`src/codeagent/session/manager.py`、`src/codeagent/ai/transport/openai_compat.py`、`src/codeagent/tools/atomic/bash.py`、`src/codeagent/tools/mcp/client.py`、`src/codeagent/tools/mcp/loader.py`。
- 主要测试：`tests/core/test_loop.py`、`tests/session/test_session.py`、`tests/session/test_session_manager.py`、`tests/tools/test_tools.py`、`tests/mcp/test_mcp.py`、`tests/test_container.py`。
- 可能新增轻量运行时协议或资源句柄，但不改变现有 `AgentPorts` 的核心调用方式；如需异步关闭，将在组合根和生命周期入口处理，避免 `core` 依赖具体模型或工具实现。
- 不新增第三方运行时依赖；继续使用现有 `asyncio`、`subprocess`、MCP SDK 和 HTTP 客户端。
- 兼容性风险：新增错误/状态 metadata，事件类型保持不变；非法参数不再触发真实工具执行，属于预期的安全行为变化。
