## 1. 核心事件与状态契约

- [x] 1.1 在 `core/contracts/events.py` 增加 Subagent 排队、启动、进度和终态事件类型，以及父/子序列和子事件类型所需的兼容字段归一规则。
- [x] 1.2 将 `SubagentState` 接入活动委派记录，固定从 queued、starting、running/等待确认、cancelling 到唯一终态的合法转换，并保留预算失败的 `failed + budget_exceeded` 语义。
- [x] 1.3 增加 core 契约测试，覆盖事件关联、run_id 归属、两套序列隔离、状态转换和重复终态保护；确认旧 metadata-only 事件仍可读取。

## 2. 父级事件转发与运行器治理

- [x] 2.1 新增有界 Subagent 事件 envelope/摘要构造逻辑，将子事件映射为状态、阶段、工具操作、耗时、reason code 和序列，不携带完整 transcript 或无界 payload。
- [x] 2.2 修改核心工具调用桥接，使专用 Subagent 事件直接进入父 Agent 事件流，普通工具 update 仍保持 `TOOL_EXECUTION_UPDATE`/`tool_progress` 兼容路径。
- [x] 2.3 修改 Session runtime 的关联事件路由：允许专用子事件跨 child run 转发到父级 EventBus，分配父级接收序列，但不推进父运行的 `RunPhase` 或覆盖父 run_id。
- [x] 2.4 在串行 Subagent runner 中发布 queued/started/progress/finished 事件，接入状态提交点，保证正常完成、启动/执行失败、预算耗尽、超时和父级取消各有唯一终态事件。
- [x] 2.5 增加关闭闸门、迟到事件诊断和观察者异常隔离，确保终态后不再转发过程事件、不重新加入活动表，且 cleanup_uncertain 保持诚实并有界。

## 3. 运行回归与边界测试

- [x] 3.1 使用 Fake child/session 覆盖排队、启动、模型等待、工具运行、确认等待和取消阶段的顶层事件关联与序列顺序。
- [x] 3.2 覆盖完成/取消/超时/预算失败竞态、重复回调、迟到事件、异步观察者异常和清理不确定，断言每个 delegation 只有一个 `SUBAGENT_FINISHED`。
- [x] 3.3 增加真实 FakeClient 父子 Session 集成测试，确认父 EventBus 收到可定位的顶层 Subagent 事件、父级继续回答，且父 transcript 不包含子过程事件或完整子输出。
- [x] 3.4 回归无 Subagent runner 的单 Agent 事件顺序、工具进度和 TUI 现有事件忽略行为，确认兼容消费者不受影响。

## 4. 文档与质量门禁

- [x] 4.1 在 `docs/iteration/v0.5.md` 更新 V5-06 实现记录、验收边界和后续 TUI 展示依赖。
- [x] 4.2 运行相关窄测试、unit/contract 测试、跨边界测试、Ruff、规模扫描、`git diff --check` 和 OpenSpec strict validation。
- [x] 4.3 运行完整离线测试与 `uv build`，检查差异只包含本变更、无生成机密或用户会话数据，并准备中文 commit 描述。
