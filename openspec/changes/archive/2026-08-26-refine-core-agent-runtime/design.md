## Context

当前 `core` 已经是标准库依赖的 ReAct 实现,但 `core/ports.py` 同时承载模型响应、流事件、安全策略、摘要器和工具执行端口,`core/loop.py` 还直接管理确认队列、steer 消息和具体工具调用约定。`session/` 已经负责持久化、恢复、压缩和回滚,`app/composition/` 已经负责 AI 适配和工具装配,因此本变更采用“core Agent Runtime + session 外壳 + app 扩展”的结构,不重新引入外部编排框架。

## Goals / Non-Goals

**Goals:**

- 建立纯内存的 `AgentContext`、Agent loop 和可选的 `Agent` 状态外壳。
- 让模型、工具、上下文转换和工具前后置行为通过最小端口注入。
- 将 Agent 事件与 Session 事件分离,保留上层对现有用户体验事件的适配能力。
- 保证工具并发、超时、取消、清理和结果回填顺序可测试且契约一致。
- 让 Memory、MCP、Skill 和安全策略只能通过 context/tool/hook 适配接入。
- 迁移现有 Session、组合根和测试,确保现有功能行为在新的 core 契约上保持可用。

**Non-Goals:**

- 不在本变更中重新设计 AI provider、模型目录或传输实现。
- 不把 JSONL、session tree、compaction entry 或持久化 id 迁入 core。
- 不在 core 内实现 MCP 客户端、Skill 文件加载、系统提示词构建或安全规则解析。
- 不引入第三方 Agent/Graph 编排框架。
- 不承诺保留 `AgentPorts`、`run_turn` 和旧事件字段作为长期兼容接口。

## Decisions

### 1. 采用双层 Agent API

core 提供低层异步 loop 和高层内存 Agent:

```text
run_agent_loop / run_agent_loop_continue
        ↓
Agent (context + queues + subscribers)
        ↓
AgentSession (persistence + compaction + session events)
```

低层 loop 负责单次执行并返回本轮新增消息;高层 `Agent` 负责 prompt、continue、abort、steer、follow-up 和 Agent 事件订阅,但不负责持久化。`AgentSession` 可以持有或包装该 Agent,成功后提交新增消息,失败时回滚。

选择双层 API 而不是只保留 `run_turn` 的原因是:

- 低层 API 便于离线单测、批处理和无状态调用;
- 高层 API 为 TUI/CLI 提供类似 Pi-agent 的持续运行控制;
- Session 不再需要通过 `before_ids` 猜测 core 返回的是整段历史还是新增消息。

### 2. core 定义运行时消息,AI 适配器负责模型协议转换

`core.messages` 只保留 Agent 可理解的 user、assistant、tool result、tool call 和通用 details。`app/composition/model_factory.py` 将 `ai.model` 的 `ChatMessage`/AI stream event 转换为 core 的模型端口事件;core 不再调用 provider 原始参数 JSON 解析。

消息 id 保留为 Agent Runtime 的事件和工具归属标识,但 `parent_id`、压缩虚拟消息、分支关系和 JSONL 编解码属于 `session`。工具特定的退出码、截断信息和产物路径进入 opaque `details`,不继续扩展 core `ToolResult` 字段。

选择适配器边界而不是让 core 直接复用 `ai.model` 类型,是因为仓库约束要求 core 不反向依赖 ai;同时避免在 core 与 ai 各维护一套可互相泄漏的 provider 协议。

### 3. 将安全策略建模为通用工具 hook

core 只执行通用的 `before_tool_call` / `after_tool_call`。`ApprovalPolicy`、确认队列、headless fail-closed、TUI 确认请求由 app/session 适配器实现:

```text
before_tool_call
  ├─ allow   → ToolExecutor
  ├─ block   → structured error ToolResult
  └─ ask     → app/session 等待确认后返回 allow/block
```

这样 Bash/MCP/只读模式的安全规则可以在上层组合,主循环无需知道“确认”来自 TUI、headless 或其它宿主。

### 4. 工具执行协议统一为 AgentTool

执行器不再假设 `tool.Args`、`invoke` 或特定 Pydantic 结构。core 只要求工具暴露名称、描述、参数 schema 和异步执行入口,并可接收取消信号和进度回调。Atomic Tool、MCP Tool 和测试 Fake Tool 分别在 `tools/` 或组合根提供适配器。

统一执行路径由组合根创建一个共享 executor 并注入 Agent;移除 loop 中每次调用都新建运行时的死路径。执行器同时记录 operation id、状态、清理确认和结果顺序,`ToolExecutionRuntimePort` 的签名与实际调用保持一致。

### 5. Agent 事件与 Session 事件分层

core 事件采用 Agent 生命周期:

```text
agent_start
  turn_start
    message_start/update/end
    tool_execution_start/update/end
  turn_end
agent_end
```

`session_started`、`restore_started`、`compaction_started`、`confirmation_requested` 等由 session/app 产生。Session 可以订阅 core 事件并继续向现有 EventBus 发布外部兼容事件,但 core 不再为这些应用生命周期保留字段。

选择事件分层而不是直接删除所有旧事件,是为了让 TUI/CLI 迁移可以分阶段完成,并允许外部消费者在 Session 适配层继续获得稳定的用户体验事件。

### 6. 扩展只通过四类显式入口进入

扩展能力映射如下:

| 能力 | 接入点 | 所属层 |
|---|---|---|
| Memory | `transform_context` | session/app |
| MCP | `AgentTool` provider | tools/app |
| Skill | system prompt/tool provider | app |
| 安全策略 | `before_tool_call` / `after_tool_call` | app/tools |
| 压缩 | Session 在 turn 边界触发 + `transform_context` | session |

扩展接收结构化输入并返回明确结果,不通过修改 `core.loop` 或全局状态注入。

## Risks / Trade-offs

- [Risk] `AgentPorts`、`run_turn` 和旧事件是仓库内部多个测试与 Session 的直接依赖 → [Mitigation] 先增加新 loop/Agent 契约和适配层,按 core → composition → session → TUI 顺序迁移,最后删除旧入口并用边界测试阻止回流。
- [Risk] 将 system prompt 和工具输出细节移出 core 后,模型可见上下文或 UI 诊断可能丢失 → [Mitigation] 在组合根保留 system prompt 构建,在 `ToolResult.details` 保留结构化元数据,增加 end-to-end 事件与模型请求断言。
- [Risk] 并行工具的完成事件顺序与消息回填顺序不同,消费者可能误用事件顺序 → [Mitigation] 明确事件按真实完成顺序、tool result 消息按调用顺序,事件携带 operation id 和 index。
- [Risk] hook 异常可能破坏工具执行或 Session 收尾 → [Mitigation] hook 阶段进入统一错误事件和回滚路径,不静默吞掉异常;对取消异常保持取消语义。
- [Risk] 共享执行器改变并发和资源生命周期 → [Mitigation] 由组合根显式拥有 executor,Agent close/Session close 触发 cancel_all 和资源释放,增加并发、超时、取消回归测试。
- [Risk] 过度追求 Pi API 造成 Python 项目不必要的抽象 → [Mitigation] 只引入与当前需求直接相关的双层 API、四类 hook 和统一工具协议,不复制 Pi 的 TypeScript 类型系统或扩展加载机制。

## Migration Plan

1. 在 core 中定义新的消息、模型端口、AgentTool、AgentContext、AgentLoopConfig、hook 和 Agent 事件类型,同时保留旧实现用于迁移期间对照。
2. 抽出独立的模型适配器,把 `ai.model` 事件转换为 core 模型事件;将原始参数解析和 system prompt 处理留在组合根。
3. 统一 `ToolExecutionRuntime` 端口、operation id、取消和进度协议,迁移 Atomic Tool、MCP Tool 和 Fake Tool。
4. 实现低层 loop 和内存 Agent,覆盖 prompt/continue、steer/follow-up、hook、并发工具、取消和事件顺序。
5. 将 `AgentSession` 改为 core Agent 的持久化外壳,把 Session 生命周期事件、compaction、restore、rollback 和 usage 统计留在 session。
6. 迁移 app/container、TUI、CLI 和测试到新事件及新入口,保留必要的 Session 级用户体验事件适配。
7. 删除旧 `AgentPorts`/`run_turn` 专用路径、确认队列直连和 core 中的 system prompt 规格,更新架构文档与依赖方向测试。
8. 验证顺序:core 单测 → session/composition/tools 测试 → 全量测试;失败时可在删除旧入口前回滚到上一迁移阶段。

## Open Questions

- 当前外部调用方是否存在直接导入 `codeagent.core.run_turn` 的仓库外使用者;若存在,需要在破坏性迁移说明中明确版本边界。
- 是否需要把 Python async generator 直接作为公开事件流,还是由现有 EventBus 继续提供宿主订阅;该选择不影响核心 hook 和消息契约,可在实现阶段根据 TUI 迁移成本确定。
