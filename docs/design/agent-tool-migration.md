# AgentTool 工具协议迁移

当前 `core` 的唯一工具入口是 `AgentTool.execute(tool_call_id, arguments, signal, on_update)`。`core` 不读取 `Args`、`args_schema`，也不调用 `invoke`、`ainvoke` 或 `invoke_async`。

## 组合根适配

内建 AtomicTool 和 MCP 工具仍可保留各自的 schema、进程和客户端实现，但进入 `AgentLoopConfig.tools` 前必须通过：

```python
from codeagent.app.composition.tools.adapter import adapt_tools

config.tools = adapt_tools(raw_tools)
```

`AgentToolAdapter` 在应用组合层完成 Pydantic 参数校验、异步入口、同步调用的线程封装、结果转换和取消能力声明。MCP 工具的名称继续使用 `mcp__<server>__<tool>`；组合根只把适配后的对象交给 core。

## 直接使用 core

纯 core 调用方应直接实现 `AgentTool`：提供 `name`、`description`、provider-neutral 的 `parameters` 和异步 `execute`，并返回 `ToolResult`。需要外部资源清理时，额外实现 `ToolCleanupPort.cleanup(operation_id)`；没有可验证抢占能力的同步封装必须报告 `unsupported`/`uncertain`，不能声称已终止。

旧式对象若未经适配传入 `ToolExecutionRuntime`，会收到可诊断的工具契约错误，不会触发其旧 `invoke` 入口。这是有意的 breaking change；仓内手工构造 `AgentLoopConfig` 的调用方应在配置边界完成迁移。
