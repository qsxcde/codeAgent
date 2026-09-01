## Why

当前子 Agent 返回给父 Agent 的结果主要是摘要、状态和诊断，父 Agent 无法稳定区分“结论”“证据”“用量”和“可继续追踪的产物”。如果继续把这些事实编码在自然语言或完整子 transcript 中，长会话会膨胀，结果也难以被 TUI、后续持久化和自动治理复用。V5-05 现在补齐结构化结果边界，为后续事件展示和有限运行记录提供稳定输入。

## What Changes

- 为 core 增加 provider-neutral 的结构化结果值对象：发现、证据、用量和可选 artifact 引用。
- 扩展 `SubagentResult`，在保持现有构造兼容的前提下返回这些有界字段，并提供 JSON-safe 的字典表示。
- 从子会话最终消息、工具输出元数据和 usage 观察中提取有限证据、artifact 引用和用量；不复制完整子 transcript，也不解析任意自然语言为不可靠的发现。
- 将结构化字段一并映射到父 Agent 可消费的 `ToolResult.details`，成功和失败结果均保留状态、诊断及清理不确定性。
- 对数量、字符长度、token 数和引用文本实施硬边界，拒绝不合法的结构化结果，避免结果回传成为无界输入通道。
- 增加 core 契约、组合层提取和 FakeClient 集成回归测试，并更新 V5.05 规格与实现记录。

## Capabilities

### New Capabilities

<!-- 本阶段扩展已有 Subagent 能力，不新增独立 capability。 -->

### Modified Capabilities

- `subagent-runtime`: 将有界结果回传从摘要/诊断扩展为结构化发现、证据、用量和可选 artifact 引用，并规定提取、序列化和边界行为。

## Impact

- 影响 `src/codeagent/core/contracts/subagents.py` 及 core 公共导出，新增稳定的 provider-neutral 数据类型。
- 影响 `src/codeagent/app/composition/subagent/` 的子结果提取和 `delegate` ToolResult 适配；不改变子 Session 持久化格式，也不把临时子会话加入普通会话列表。
- 影响相关 core/app 测试、V5.0.5 迭代记录和 OpenSpec 主规格同步内容。
- 不新增第三方依赖，不改变旧调用方只使用 `summary`、`failure` 或 `diagnostics` 的行为。
