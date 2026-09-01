## Why

V5-02/V5-03 已经能够启动隔离的只读子 Agent，但当前 `SubagentBudget` 仅停留在请求契约层，运行器没有强制轮数、工具调用数、父运行子任务数或墙钟时间。子 Agent 也没有统一覆盖排队、确认等待、取消、超时和关闭异常的收尾边界，长时间运行或不合作的子会话可能拖住父 Agent，并把未确认清理误报为成功。

现在补齐这层治理，可以在继续扩展结果和 TUI 可观察性之前，先固定 Subagent 的资源上限、终止语义和安全失败行为。

## What Changes

- 为 `delegate` 增加可选的结构化 budget 参数，并使用显式的安全默认值和硬上限：每个父运行最多 4 个子任务；单个子运行默认最多 8 轮/32 次工具调用/120 秒/8000 字符摘要，允许的上限分别为 16/64/300 秒/16000 字符。
- 在请求入口和运行器再次校验预算，拒绝类型错误、非有限数值和超过硬上限的请求，避免模型输入绕过应用层边界。
- 将子运行的轮数映射到现有 Agent 循环，将工具调用计数绑定到子事件，将父运行子任务数绑定到执行副本；达到上限时停止子运行并返回 `failed + budget_exceeded`。
- 让墙钟预算覆盖串行队列等待、子 Session 启动、模型/工具执行和确认等待；超时时先请求取消并执行有界收尾，返回 `timed_out + timeout`。
- 统一父级取消、预算取消和超时的区分：父级取消返回 `cancelled + parent_cancelled`，预算耗尽保留 `budget_exceeded`，未知/已完成委派仍不影响其它运行。
- 为取消、超时、启动失败和关闭失败增加有界清理等待；清理失败或无法确认时，在 `SubagentResult`/`ToolResult` 中保留 `cleanup_uncertain`，不得宣称资源已清理。
- 增加排队取消、确认等待取消、墙钟超时、预算耗尽、不可合作清理和父级继续运行的离线回归测试，并同步 V0.5 OpenSpec/迭代记录。

## Capabilities

### New Capabilities

无。本变更是在现有 Subagent runtime 能力上补齐运行时约束。

### Modified Capabilities

- `subagent-runtime`: 委派入口增加有界预算，独立子运行必须执行预算和清理边界，取消定位扩展为超时/预算/父级取消的明确终态语义。

## Impact

- 影响 `src/codeagent/app/composition/subagent/` 的 delegate 适配器、串行运行器、子 Session 工厂和清理辅助模块。
- 影响 `src/codeagent/core/contracts/subagents.py` 的结果诊断字段，但保持现有构造参数和旧请求的向后兼容；未提供预算的调用使用默认策略。
- 不新增第三方依赖，不改变父 Session 的持久化格式或普通单 Agent 行为；只读子 Agent 继续复用现有 ApprovalPolicy、工具资源限制和 Session 生命周期。
- 新增/修改 `tests/app/`、`tests/core/` 的契约与集成回归，并更新 `docs/iteration/v0.5.md`。
