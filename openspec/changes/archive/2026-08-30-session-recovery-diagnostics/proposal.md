## Why

会话文件和派生索引可能因进程中断、手工修改、版本演进或部分写入而损坏。当前读取路径要么静默跳过坏记录，要么以通用异常阻断恢复，用户无法知道丢失了什么，也没有明确的继续、备份或升级路径；V4-26 需要把这些结果变成可解释、可操作的恢复体验。

## What Changes

- 为会话恢复增加结构化报告，区分完整恢复、局部降级和不可安全恢复，并保留稳定错误码、影响范围和建议动作。
- 对坏 JSONL 行、无效消息、缺失压缩切点和可重建索引提供尽可能的局部恢复；结构性 header/版本问题保持原文件不变并阻止不安全继续。
- SessionManager、TUI 和 headless `--session` 入口展示恢复报告，不把可恢复问题伪装成普通空会话，也不触发模型请求来“修复”数据。
- 提供按会话查询恢复诊断的入口，提示用户可执行的备份、导出、升级或新建会话操作；正常会话行为保持不变。

## Capabilities

### New Capabilities

<!-- 本变更修改已有会话与 TUI 能力，不新增独立能力。 -->

### Modified Capabilities

- `sessions`: 会话读取和恢复需要返回可判断的诊断，并允许有效部分继续使用。
- `tui`: 会话切换、恢复和 headless 指定会话失败时需要显示结构化、可操作的诊断。

## Impact

影响 `session/persistence` 的 JSONL 读取与索引恢复、`SessionPersistence`/`SessionManager` 的恢复边界、TUI 会话命令和 CLI 入口；不新增外部依赖，不改变 JSONL 已有记录格式，不覆盖或自动删除原始会话文件。需要补充 MemoryStore/JsonFileStore、manager、TUI 和 CLI 的离线回归测试及恢复文档。
