## Context

本变更建立在 `openspec/specs/core/spec.md`、`openspec/specs/tools/spec.md` 以及正在收尾的 context-budget 变更之上。当前 core 的分层 import 已经正确,但 `ToolExecutionRuntime` 和 `new_tool_result` 仍通过属性探测兼容旧式 `Args/invoke/ainvoke` 工具,`execution.py`、`loop.py` 中的单个函数也同时管理调用、清理、并发和生命周期。

实现必须保持 `core` 只依赖标准库和 core 自身类型;具体内建工具、MCP client、Pydantic schema、进程和文件系统能力留在 `tools/` 或 `app/composition/`。`TransformContext`、上下文预算、消息/事件字段、session 提交边界和公共 `codeagent.core` 导出继续保持现有语义。

## Goals / Non-Goals

**Goals:**

- 让 core 只消费明确的 `AgentTool`、`ModelPort` 和 `ToolExecutionRuntimePort` 协议,不再识别具体工具对象的历史属性。
- 通过显式工具适配器把内建工具和 MCP 工具装配为统一的 AgentTool,由组合根负责挂载。
- 将工具执行状态、结果归一化、清理和 ReAct 工具批次拆为可独立测试的模块。
- 保持并行/串行执行、调用顺序、超时、取消、清理诊断、事件顺序、steer、follow-up 和失败回滚语义不变。
- 保持 `codeagent.core` 当前规范导出,减少调用方只因内部拆分而修改 import。

**Non-Goals:**

- 不改变 CLI/TUI 入口、会话 JSONL、消息父子关系、上下文预算字段或 provider 协议语义。
- 不删除 `TransformContext` 的兼容入口;它属于上下文扩展契约,不属于本次移除的工具执行兼容。
- 不在 core 中实现工具安全策略、MCP 生命周期、Pydantic schema 解析、文件访问或子进程管理。
- 不引入新的第三方依赖,不把所有工具重写成新的业务实现。

## Decisions

### 1. 以 AgentTool 作为唯一 core 工具协议

扩展 `AgentTool` 使工具具备名称、描述、provider-neutral 参数定义、异步 `execute` 和清理契约。`execute` 接收 tool call id、参数、取消信号和进度回调,返回 core 可消费的 `ToolResult`;超时/取消清理返回统一的 `CleanupStatus` 或等价结构化状态。运行时不再使用 `getattr` 探测 `Args`、`args_schema`、`invoke`、`ainvoke` 或 `invoke_async`。

这样可以把“工具如何校验参数、如何在线程或进程中执行、如何停止底层资源”归还给工具适配层。备选方案是在 core 新建 `legacy_adapters` 子包继续托管旧协议,但这仍会使 core 绑定历史实现形态,只把耦合隐藏起来,因此不采用。

### 2. 在 tools/composition 建立显式适配边界

新增工具层适配器,负责把现有 AtomicTool 和 MCP tool 转换为 AgentTool。适配器负责生成 `parameters`、在异步入口中调用底层实现、把具体结果映射为 `ToolResult`,并把底层取消/清理事实转换为 `CleanupStatus`。同步底层实现由适配器使用线程封装,core 只看到异步 AgentTool;无法抢占的同步调用必须报告 `unsupported`/`uncertain`,不能伪装为已停止。

组合根只把适配后的工具列表放入 `AgentLoopConfig`;不允许存在“部分工具走 AgentTool、部分工具依赖 core 旧 fallback”的混合装配。模型适配器可继续接收 AgentTool 并将其序列化为 provider 工具定义,但 schema 解析不进入 core。

### 3. 保留稳定 façade,按职责拆分实现

公共 `codeagent.core` re-export 不变,内部按以下边界重组:

```text
core/
├── execution.py          # ToolExecutionRuntime façade 与公共运行入口
├── execution_state.py    # ToolOperation、OperationRegistry
├── execution_cleanup.py  # timeout/cancel/cleanup 状态流程
├── execution_result.py   # ToolResult 状态和清理字段归一化
├── loop.py               # run_agent_loop 生命周期与公共入口
├── turn.py               # 单轮模型请求、steer 和 stop 判定
├── tool_batch.py         # 工具批次并发、顺序和取消收尾
└── tool_result.py        # 单个工具调用前后钩子与结果构造
```

`tool_invocation.py` 在确认无外部导入后删除,其单工具 hook 逻辑迁移到短的 `tool_result.py`。`context_budget.py`、`context_preflight.py`、`messages.py`、`events.py` 和 `context.py` 保持独立,不把预算或持久化逻辑塞进执行器。

### 4. 工具执行生命周期由 runtime 统一拥有

`ToolExecutionRuntime.execute` 只负责创建 operation、获取并发槽、调用 AgentTool、处理 timeout/cancel、记录 cleanup 和返回结构化结果。具体的参数解析和执行方式不再由 runtime 决定。工具批次负责收集多个 operation 的完成结果,以原始 tool-call 顺序回填,以真实完成顺序发布事件。

清理流程保持保守原则:异步执行确认停止时才报告 confirmed;清理钩子失败报告 failed/uncertain;线程封装的同步执行无法确认停止时报告 unsupported/uncertain。取消路径仍等待可等待的清理任务,不释放未完成 operation 的状态保证。

### 5. 模型请求只使用中立工具元数据

`model_request.neutral_tool_definitions` 只读取 AgentTool 的 `name`、`description` 和 `parameters`,删除 `args_schema.model_json_schema()` fallback。模型请求仍在隔离消息副本上执行 `TransformContext` 和预算 preflight,不会修改 session 原始历史。

### 6. 采用分阶段迁移而不是一次性替换

先建立严格协议和适配器测试,再切换 composition 装配,最后删除 core fallback 和拆分模块。每个阶段保留同一组行为测试,并通过 AST 检查禁止 core 出现旧工具属性访问。公共 re-export 最后核对,不使用临时兼容入口掩盖内部调用方未迁移。

## Risks / Trade-offs

- **[内建工具和 MCP 工具返回形态不一致]** → 先在适配器边界统一为 `ToolResult` 和 `CleanupStatus`,为每类工具增加离线契约测试。
- **[删除 fallback 导致隐藏调用方失败]** → 迁移前用 `rg` 扫描所有旧式 core 调用,增加未适配工具的明确装配失败测试,不在 core 中静默回退。
- **[取消/超时语义回归]** → 保留现有运行时清理测试,补充 AgentTool 的 async、同步线程和 cleanup hook 三类契约测试。
- **[拆分导致循环 import]** → 先抽取只依赖 core 消息/状态的低层模块,由 `loop.py` 和 `execution.py` 作为向上依赖点;每批迁移运行导入边界测试。
- **[context-budget 变更仍在收尾]** → 不删除 `TransformContext` 或预算端口,仅调整工具类型和内部 import;在两个 active change 完成前不改动持久化边界。
- **[测试误把真实工具当作 core 单元依赖]** → 将真实 Bash/MCP 适配测试标记为 contract/integration,core 单元测试使用本地 fake AgentTool。

## Migration Plan

1. 新增严格 `AgentTool`/清理契约测试,盘点并固定现有工具结果、超时、取消和事件行为。
2. 在 `tools/` 或 `app/composition/` 实现 AtomicTool/MCP 到 AgentTool 的显式适配,更新组合根只挂载适配后工具。
3. 收紧 `ports.py` 类型,让 `ToolExecutionRuntime`、工具批次和模型请求仅接收 AgentTool;删除 core 中旧 schema/invoke 分支。
4. 拆分 `execution.py`、`loop.py` 和 `tool_result.py`,删除 `tool_invocation.py`,保留 `core/__init__.py` 的稳定 re-export,逐批迁移内部 import。
5. 更新测试分类和架构/规模扫描,确认 core 无 `Args`、`args_schema`、`invoke`、`ainvoke` 兼容探测。
6. 运行 core/contract 窄测试、Ruff、OpenSpec 验证、完整离线测试和构建检查。

回滚时按迁移批次恢复 composition 装配和内部模块导入;不涉及 JSONL 或消息格式迁移。由于旧工具调用契约是明确的 breaking change,发布前必须完成所有仓内调用方迁移,不能通过运行时 re-export 或隐式 fallback 回滚。

## Open Questions

无。AgentTool 的清理返回形态、适配器所在层和兼容范围均已在本设计中确定;若实现中发现具体 MCP 工具无法满足该协议,应新增适配器而不是扩大 core 的兼容范围。
