## Context

See proposal.md - Why. 当前 core 已有 `transform_context` 和 `context_preparer` 两个可注入入口，模型请求准备逻辑负责复制消息、计算预算和治理工具结果，但尚未集中定义扩展返回值校验与超时边界。

## Goals / Non-Goals

**Goals:**

- 用 provider-neutral 的类型协议描述旧式与预算感知上下文扩展。
- 在每次模型请求范围内隔离输入和输出，验证消息集合，并保留现有组合顺序。
- 让可选超时对扩展等待生效，区分超时、普通失败和取消。
- 保持现有同步/异步回调兼容、持久化格式和错误事件链路。

**Non-Goals:**

- 不在本变更中实现自动压缩、记忆策略或新的上下文扩展实现。
- 不强制迁移现有调用方的 `transform_context` 参数名称。
- 不在 core 引入 provider、session、MCP、Skill 或新的第三方依赖。

## Decisions

1. **保留兼容别名并增加显式协议。** 使用 `ContextTransformer` 描述消息列表转换 callable，保留 `TransformContext` 作为兼容别名；这样既能让类型和文档表达稳定契约，也不会破坏现有构造调用。

2. **在请求准备边界统一物化和校验结果。** 扩展结果先被物化为 list，再逐项确认是 `Message`，所有消息继续深复制后才进入后续预算和 provider。相比让 provider 或下游在深处报错，这能把错误归类为上下文准备失败并确保原始历史不受影响。

3. **超时配置作用于每个扩展调用。** 新增可选正数 `context_transform_timeout`，分别限制 legacy transformer 和 budget-aware preparer 的等待时间；超时抛出带稳定错误码的 `ContextTransformTimeoutError`。异步回调在当前任务中等待，同步回调在启用超时时通过线程隔离执行，以便请求边界及时返回；线程中的同步工作无法被 Python 强制抢占，调用方仍需避免不可控的长时间阻塞 I/O。

4. **失败不隐式回退，取消不包装。** 扩展失败或非法输出直接终止本次模型请求，已有 `ContextPreparationError` 事件映射继续负责诊断；`CancelledError` 保持 BaseException 语义向上传播，避免取消被当作业务失败。

5. **配置校验在组合根之前完成。** `AgentLoopConfig` 验证超时是有限正数，避免负数、布尔值、NaN 和无穷值进入请求执行；默认 `None` 保持当前无超时行为。

## Risks / Trade-offs

- [同步扩展不可抢占] Python 无法安全强制终止已经运行的同步回调 → 超时只保证 Runtime 不继续等待，隔离线程可能继续运行；要求同步扩展保持短小且不产生不可逆外部副作用。
- [严格输出校验暴露潜在兼容问题] 过去某些扩展可能返回惰性消息迭代器 → 仍接受可迭代结果并在边界物化，只拒绝 `None`、文本和非 Message 项。
- [每次深复制增加少量开销] 隔离是持久化安全的前提 → 复用现有 clone 逻辑，仅在扩展边界复制，不改变存储格式。

## Migration Plan

1. 增加协议、错误类型、配置字段和请求准备辅助函数。
2. 先补充扩展顺序、隔离、非法返回、超时和取消回归测试，再接入实现。
3. 同步 OpenSpec 与 v0.4 进度文档；默认配置无需迁移。
4. 如需回滚，移除新的超时配置并恢复旧请求准备实现，持久化数据无需迁移。
