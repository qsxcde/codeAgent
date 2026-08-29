## Why

v0.4 已具备手动压缩和基于最近一次 provider usage 的阈值压缩，但当前策略没有完整考虑下一次请求的 system prompt、工具定义、工具结果、输出预留和模型窗口变化。压缩触发过晚或过早、重复触发，以及压缩失败后错误影响已提交轮次等问题，会降低长会话的可预测性和可恢复性。

## What Changes

- 将自动压缩触发依据统一为下一次模型请求的有效输入预算，而不是固定窗口余量或单独的 `last_input_tokens`。
- 增加可配置的自动压缩触发阈值、压缩目标、绝对余量和最近轮次保留策略，并支持滞后区间避免重复压缩。
- 将压缩流程拆分为计划、摘要、预算验证和异步持久化阶段；压缩结果不满足目标预算或没有安全边界时返回结构化跳过原因。
- 保持完整 user turn 边界、增量摘要链、文件操作和关键错误信息，不删除 JSONL 中的物理历史。
- 增加自动压缩的单飞、上下文指纹和失败冷却，避免手动压缩与自动压缩并发或重复执行。
- 将压缩诊断接入现有事件流和 TUI，包括触发原因、前后预算、保留/摘要轮次和失败原因。
- 解耦“本轮消息已成功提交”和“提交后的自动压缩失败”两种状态；压缩失败或取消不得否定已提交的对话轮次。
- 保持请求前 preflight 只负责预算判定，不在 core 层隐式执行压缩；session 层消费预算结果并负责生命周期协调。

## Capabilities

### New Capabilities

<!-- No standalone capability is introduced; the behavior extends existing session and budget contracts. -->

### Modified Capabilities

- `sessions`: 将上下文压缩扩展为基于下一次请求预算的自动策略，并定义压缩计划、结构化跳过/失败语义、并发协调和提交后状态。
- `context-budget`: 扩展预算事实来源，使自动压缩能够使用包含完整请求组成的下一次请求预算、有效输入预算和模型窗口变化后的重新估算。
- `tui`: 展示自动压缩过程、结果和诊断，并在压缩期间阻止冲突操作。

## Impact

- 影响 `src/codeagent/session/compaction/`、`compaction_runtime.py`、`run_coordinator.py` 和 `session.py` 的运行时策略与状态管理。
- 影响 `src/codeagent/core/context/` 的预算视图/接口，但不把压缩逻辑引入 core，也不绑定 provider、工具或持久化实现。
- 影响 TUI 的结构化事件消费和状态栏/活动提示；现有手动 `/compact` 入口保持兼容。
- 需要补充 session、context budget、恢复/分叉、取消/失败、TUI 事件和回归测试；不新增第三方依赖，不改变 JSONL 历史的追加式格式。
