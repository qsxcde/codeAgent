## Why

V4-11 至 V4-14 已分别实现上下文预算、请求前检查、自动压缩和工具结果治理，但现有测试主要验证单个模块，尚未系统证明进程重启后仍能把这些状态正确组合起来。压缩后的逻辑上下文、JSONL 中保留的物理历史、分叉父级链、模型切换预算以及 TUI 恢复投影需要一组跨后端、跨生命周期的回归契约，确保长期会话可以安全继续。

## What Changes

- 为未压缩会话建立冷启动恢复与继续对话的端到端回归契约。
- 为单次和多次压缩建立“最新摘要 + 保留窗口”恢复契约，验证摘要虚拟消息只进入模型请求、不重复落盘。
- 验证压缩后继续对话的新消息父级链、压缩记录链和物理 JSONL 历史保持正确。
- 对 `MemoryStore` 与 `JsonFileStore` 建立一致的恢复、压缩和分叉行为矩阵。
- 验证压缩会话在保留窗口内和压缩边界之前分叉后的恢复语义、`parentSession` 和子会话继续能力。
- 验证恢复后切换模型时，下一次请求预算基于新模型重新计算，既有历史、压缩记录和累计 usage 不被改写或重复使用。
- 将结构化工具结果 metadata、旧 JSONL 兼容状态和不可恢复截断状态纳入恢复回归。
- 验证 TUI 恢复摘要、工具结果和上下文状态的投影，以及异步大历史恢复结果不会覆盖已切换的当前会话。

## Capabilities

### New Capabilities

无。本变更强化现有会话恢复、上下文预算和 TUI 恢复能力。

### Modified Capabilities

- `sessions`: 明确压缩、重启、继续、分叉和模型切换组合后的逻辑上下文、物理历史、工具 metadata 与父级链恢复要求。
- `context-budget`: 明确恢复后的逻辑上下文和模型切换必须作为下一次请求预算的唯一输入，不能复用旧模型预算或累计 usage。
- `tui`: 明确恢复摘要、结构化工具结果和异步恢复过期保护的可观察行为。

## Impact

- 主要影响 `src/codeagent/session/persistence/`、`src/codeagent/session/compaction*`、`src/codeagent/session/run_coordinator.py` 和 `src/codeagent/session/manager/` 的集成测试与必要修复。
- 影响 `src/codeagent/app/tui/session/restore.py`、TUI 状态投影及工具结果恢复展示测试。
- 新增或扩展 `tests/session/behavior/`、`tests/session/store/`、`tests/tui/` 中的离线回归测试，使用 `FakeClient`、确定性 summarizer、`tmp_path` 和双 Store 参数化。
- 不新增依赖，不改变现有 JSONL 文件格式的兼容读取，不删除物理历史，不改变工具调用协议或模型 provider 接口。
