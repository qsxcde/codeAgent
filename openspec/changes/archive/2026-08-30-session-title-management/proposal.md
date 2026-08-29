## Why

会话已经能够从首条用户消息派生标题，也已有 append-only 的 `name` 元数据机制，但用户无法通过稳定的产品入口重命名会话。会话数量增加后，只有截断的自动标题难以区分主题；现在补齐手动命名和安全归一化，可以改善列表、恢复和分支导航，同时不改写历史。

## What Changes

- 增加 `SessionManager.rename` 会话标题操作，统一校验、归一化并通过 `SessionStore` 持久化显示名。
- 增加 TUI `/name <title>` 命令，显示当前标题、设置新标题并对无当前会话、无持久化后端、空标题等情况给出可操作提示。
- 将自动标题和显式标题统一限制为安全、有限长度的单行展示文本；保留首条用户消息派生作为未命名会话的回退。
- 保持 JSONL append-only、历史消息、压缩记录、fork 的 `parentSession` 和现有 `/sessions`、`/tree` 展示语义不变。
- 增加 MemoryStore、JsonFileStore、SessionManager、TUI 命令和重启/分叉回归测试及文档说明。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `sessions`: 会话标题支持安全的自动派生和公开的手动重命名操作。
- `tui`: 增加 `/name` 命令及命名结果、错误状态的可见反馈。

## Impact

- 影响 `src/codeagent/session/persistence/`、`src/codeagent/session/manager/` 和 `src/codeagent/app/tui/commands/`。
- 影响 `openspec/specs/sessions`、`openspec/specs/tui`、Session/TUI 测试和 v0.4 迭代文档。
- 不新增依赖；不改变 JSONL 历史消息格式，标题继续以独立 `meta` entry 追加保存。
