## Context

参见 `proposal.md`。当前工具执行器已经具备 operation id、超时和最佳努力清理，但清理确定性与实际清理结果没有完全绑定；`SessionRuntime`、`AgentSession` 和 `SessionManager` 的停止入口也没有统一等待机制。现有 MCP 和 subprocess 实现各自拥有关闭逻辑，本变更只统一生命周期协议，不重写工具业务实现。

## Goals / Non-Goals

**Goals:**

- 建立取消请求到资源清理完成的可观察链路。
- 确保确认等待、steer、follow-up 和会话切换不产生悬挂任务或交错运行。
- 使工具清理状态基于实际结果，而不是基于“是否存在取消方法”的能力猜测。
- 让 MCP、subprocess、模型客户端都能接入统一的等待式关闭协议。

**Non-Goals:**

- 不改变 bash 的平台选择策略和工具的安全分类规则。
- 不实现通用的自动重试；清理不确定时默认禁止重试。
- 不把资源管理器、确认队列或 TUI 状态逻辑放进 core ReAct 算法。

## Decisions

### 1. 取消分为 request、propagation 和 finalized

`abort()` 只负责幂等地发出取消请求并立即返回；Runtime 内部继续等待模型、工具、确认和清理任务结束；`cancel_and_wait()` 或 `wait_for_idle()` 才代表取消流程完成。

选择该方式是为了保留 TUI 快速响应，同时避免把“按下取消键”误报为“子进程已经消失”。备选方案是让 `abort()` 同步阻塞等待，无法适配当前事件循环，拒绝采用。

### 2. 使用 OperationRegistry 汇总活动操作

每个工具 operation 登记 task、operation id、取消状态、资源清理任务和清理结果。运行收尾只在活动 operation 为空或所有 operation 已明确进入 confirmed/failed/uncertain 后完成。对不可抢占的同步工具保留 uncertain，不伪造成功清理。

### 3. 资源关闭采用异步等待协议

组合根和 SessionManager 使用等待式关闭：先停止活动运行，再关闭模型 client、MCP client、后台线程和 subprocess。对已有同步 `close()` 适配器提供异步包装，但包装必须等待实际线程/任务结束，而不是只调用方法后立即返回。

为避免在运行中切换资源，建议向上层提供 `wait_for_idle()`、`cancel_and_wait()`、`aclose()` 以及对应的异步切换/释放入口；快速同步入口只能在没有活动事件循环时阻塞等待。

### 4. 确认请求使用活动注册表

确认协调器维护 request id 到 Future/状态的映射，响应前检查请求仍处于 pending。取消和超时从注册表移除请求并唤醒等待者，过期响应返回 ignored，不进入通用队列污染未来请求。

### 5. 统一清理确定性

清理方法返回或转换为 confirmed、failed、uncertain、unsupported。工具执行器保留超时/取消的原始状态，同时通过 `cleanup_uncertain` 和 `side_effect_state` 向上层传播。这样重试策略可以依据事实决策，而不是依据中文提示。

## Risks / Trade-offs

- **[Risk]** 等待不可抢占的同步工具会延长关闭时间 → 设置清理等待上限，超限后明确返回 uncertain，并保留诊断，不无限阻塞。
- **[Risk]** 异步切换/释放 API 会增加调用方迁移成本 → 保留快速 abort 和同步适配器，优先迁移 TUI、Manager 和组合根。
- **[Risk]** MCP 或平台进程无法完整报告后代状态 → 使用 cleanup_uncertain，禁止安全自动重试，并将 operation id 写入事件。
- **[Risk]** 多个取消调用同时触发清理 → 通过 run/operation 状态和幂等 close 保护，重复调用复用同一个清理任务。

## Migration Plan

1. 为工具操作和确认请求增加状态模型及窄测试。
2. 将 `ToolExecutionRuntime` 的取消/超时接入真实清理结果。
3. 将 SessionRuntime、SessionManager 和组合根改为先等待运行再换配置或释放资源。
4. 迁移 TUI/CLI 到等待式关闭入口，并保留 `abort()` 的快速交互行为。

若迁移中出现平台回归，可先保留现有工具执行路径，但必须继续报告 cleanup_uncertain；不允许通过删除字段恢复静默清理语义。
