## Why

当前成功执行、消息提交、usage 落盘、自动压缩和 Runtime 释放并不处在同一个可验证的收尾边界，持久化或压缩失败可能绕过统一错误事件。已有测试覆盖了主要 ReAct 路径，但对提交失败、取消竞态、监听器异常、清理不确定和终态唯一性覆盖不足。

## What Changes

- 将一次运行拆分为执行、结果判定、成功提交/失败回滚、资源收尾和终态发布几个阶段。
- 保证失败或取消的轮次不会落盘不完整消息和 usage，并且成功提交后仍可继续、恢复和分叉。
- 明确持久化、自动压缩和收尾异常的错误事件与历史一致性语义。
- 建立 Runtime 契约测试矩阵，覆盖多轮 ReAct、并发工具、工具异常、超时、取消、确认和监听器异常。
- 增加事件序列、运行隔离、配置透传和资源清理的回归测试，测试使用 FakeClient 和可控的 fake tool。

## Capabilities

### New Capabilities

无。本变更验证并收紧已有 core/session 行为契约。

### Modified Capabilities

- `core`: 修改“消息归约”，明确运行失败/取消时的新增消息隔离和提交边界。
- `sessions`: 修改“usage 用量记录 entry”，明确只有成功完成且提交一致的轮次才写入 usage。

## Impact

- 影响 `src/codeagent/session/session.py` 的 run 收尾和持久化顺序，以及 `tests/core`、`tests/contracts`、`tests/session` 的测试组织。
- 可能新增 RunOutcome、提交状态和测试 fixture，但不改变记忆、MCP、Skill 等扩展职责。
- 测试默认离线、跨平台，不依赖真实 provider、密钥或网络。

## Implementation Evidence

- `RunOutcome` 与 `CommitStatus` 已成为 session run 的统一收尾结果，终态事件携带 `run_outcome`、`commit_status`、清理状态和副作用状态。
- MemoryStore 与 JsonFileStore 都通过可恢复的 turn 提交边界保护消息、usage 和上下文 token 元数据，提交失败时恢复原内容。
- 自动压缩属于已提交 turn 之后的维护阶段；压缩失败或该阶段取消不会删除已提交消息，也不会重复追加 usage。
- 新增离线契约测试覆盖两类存储、后提交压缩失败/取消、并发 JSONL 回滚、收尾期 steer 隔离、终态唯一性和核心监听器异常隔离；受影响窄测结果为 `198 passed`，未纳入真实 provider、密钥或网络测试。
