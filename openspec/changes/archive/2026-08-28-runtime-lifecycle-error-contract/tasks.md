## 1. 生命周期模型

- [x] 1.1 定义 RunPhase、RunState、RunOutcome 和终态迁移规则，覆盖启动、模型等待、工具执行、确认等待、继续、成功、失败、取消和收尾阶段
- [x] 1.2 将 SessionRuntime 的 active_run_id/current_task/last_failure 归并到统一状态边界，并为重复启动和非法迁移增加测试
- [x] 1.3 明确一次 run 的唯一终态和终态后事件抑制规则

## 2. 错误与事件契约

- [x] 2.1 定义 RuntimeFailure 和稳定错误码映射，区分模型、工具、确认、递归、持久化和压缩阶段
- [x] 2.2 为 core/session 事件补充 run_id、session_id、phase、operation_id 和终态元数据
- [x] 2.3 更新 EventMapper、TUI/CLI 消费方和错误展示，避免通过错误文本判断类别

## 3. Runtime 接入

- [x] 3.1 修改 SessionRuntime 的 Agent 配置构造，完整透传工具执行模式、后置钩子和停止策略
- [x] 3.2 将 AgentSession.run() 接入统一结果判定和终态发布流程，保留成功、失败、取消的既有外部语义
- [x] 3.3 覆盖模型异常、递归超限、工具异常和确认拒绝的结构化事件回归测试

## 4. 验证

- [x] 4.1 运行 core、session 和 contracts 的窄测试，确认既有事件和历史行为未被无意改变
- [x] 4.2 执行 OpenSpec 校验并记录变更状态，确认所有规划任务均可由后续 apply 阶段逐项验收
