## Context

已有测试分别验证 Hook、ContextTransformer 和工具执行，但没有单一入口说明 V4-32 的验收矩阵；工具结果后处理和 Hook 失败/取消的端到端事件语义尤其容易在职责重构时回退。

## Goals / Non-Goals

**Goals:**

- 用离线、确定性的测试固定五类契约：多个 Hook 顺序、取消传播、异常隔离/终止、上下文修改和工具结果修改。
- 断言扩展只影响请求临时视图或当前工具结果，不污染源上下文和持久化消息。
- 复用现有测试资源，保持测试标记和异步任务清理规范。

**Non-Goals:**

- 不设计新的 Hook API，不扩大生命周期事件集合。
- 不接入真实 provider、MCP、Skill、网络或文件系统。
- 不把测试替代为快照或时间敏感的性能基准。

## Test Matrix

1. lifecycle hooks：两个以上 Hook 按注册顺序执行，返回值不改变主流程。
2. context extensions：legacy transformer 与预算 preparer 按顺序修改临时消息；源消息保持不变。
3. tool result extension：`after_tool_call` 修改结果后，修改值进入下一次模型请求和最终消息。
4. extension failure：工具前后置扩展抛出普通异常时产生错误事件并停止本轮，不静默继续模型请求。
5. cancellation：等待上下文或工具扩展时取消，`CancelledError` 向上传播并发布取消事件，不伪装为普通扩展失败。

所有测试均以 fake model/tool 驱动，并显式检查模型调用次数和结构化事件。
