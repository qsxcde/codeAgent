## Context

V4-28 的 Hook 接入复用了 Agent 的异步监听队列：core 在 `_emit` 中调用 Hook，session 在事件相关性补充后调用 session Hook。当前两处都保留了 `(AgentEvent, Exception)`，但缺少 Hook 身份和失败阶段；`classify_*` 内部的深拷贝也位于保护范围之外。SessionRuntime 在一轮完成后会释放 core Agent，因此 core 诊断必须在释放前转移到 runtime，供 AgentSession 查询。

## Goals / Non-Goals

**Goals:**

- 为同步调用、异步等待和快照构造失败提供同一结构化诊断模型。
- 保证一个 Hook 失败不阻断同一事件的其它 Hook，也不改变主循环、持久化、取消和资源清理。
- 让 Agent 和 AgentSession 都能查询诊断；session 汇总 core 与 session 两个域。
- 兼容已有 `listener_errors` 和 `lifecycle_hook_errors` 裸错误查询，不改变存储格式。

**Non-Goals:**

- 不增加 Hook 重试、熔断、超时或失败即停策略。
- 不把 Hook 失败转成普通 AgentEvent，避免递归触发 Hook、污染运行事件序列和持久化。
- 不把诊断持久化，也不在本变更中实现 TUI 专用展示。

## Decisions

### 1. 使用不可变的 `HookDiagnostic`

在 `core.contracts.hooks` 定义冻结数据类，字段包括 `code=hook_failed`、`hook_name`、`stage`、可选 `scope/phase`、`event_type`、`run_id/session_id`、`error_type` 和 `message`，并提供 `as_metadata()` 供上层展示或遥测适配。Hook 名称使用模块和限定名；无法构造快照时使用固定的 `event_snapshot` 标识，避免把 callable 的任意 repr 写入诊断。

### 2. 在三类失败边界分别记录

```text
原始 AgentEvent
     │
     ├─ 快照构造 ──失败──▶ snapshot 诊断，跳过本事件 Hook
     │       │成功
     ▼       ▼
  Hook 同步调用 ──失败──▶ invoke 诊断，继续下一个 Hook
     │
  awaitable 收尾 ─失败──▶ await 诊断，继续运行收尾
```

捕获范围保持为 `Exception`，不吞掉 `asyncio.CancelledError`；异步任务仍加入现有任务集合，正常结束等待任务，取消路径取消并回收任务。

### 3. 保留旧接口并新增只读诊断接口

`Agent.hook_diagnostics` 和 `AgentSession.lifecycle_hook_diagnostics` 返回副本。原有 `listener_errors`/`lifecycle_hook_errors` 继续保留，仍记录对应裸异常，降低兼容风险；结构化诊断是新代码和展示层的首选接口。

### 4. SessionRuntime 转移 core 诊断

`SessionExecutionMixin.execute` 在 core Agent prompt 成功、失败或取消后读取 `agent.hook_diagnostics`，追加到 `SessionRuntime` 的累计诊断列表；`AgentSession` 的诊断属性再合并 runtime 的 core 诊断和自身 session Hook 诊断。转移发生在 `finally`，避免主流程异常时丢失观察失败信息。

### 5. 诊断只驻留内存

不发布额外 EventType，也不把诊断塞进 `AgentEvent` 或 session commit。这样既不会让诊断事件重新进入 Hook 管线造成递归，也不会改变历史 JSONL 格式；需要展示或外部遥测时由调用方读取结构化属性。

## Risks / Trade-offs

- 诊断列表会随长会话累积 → 只保存轻量不可变记录，返回副本；后续若有明确需求再增加容量策略。
- Hook 异常消息可能包含扩展自行生成的敏感文本 → 不持久化、不使用 callable repr；上层展示仍应遵守统一脱敏规范。
- 无法复制的 payload 会使该事件无法送入 Hook → 原始 Agent/EventBus 路径继续工作，并留下快照失败诊断。

## Migration Plan

1. 先新增结构化诊断和失败边界回归测试。
2. 在 core、session 和 runtime 桥接中接入记录与查询。
3. 更新文档、规格状态并运行分层测试、OpenSpec、Ruff、规模检查和构建。
4. 如需回退，删除新诊断采集即可；原有 Hook 调用和裸错误属性仍可独立工作。
