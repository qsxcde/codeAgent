## Why

当前父会话只把 `delegate` 的文本结果写入普通工具消息，结构化委派事实和实时事件不会进入持久化历史；进程重启后，已完成的子任务无法在 TUI 中恢复展示，崩溃时尚未结束的委派也无法被明确区分。V5-08 需要在不暴露子会话 transcript、不中断现有 JSONL 兼容性的前提下，建立父会话级的有界运行记录。

## What Changes

- 新增父会话专用的 `subagent` JSONL 记录，保存有界的任务标签、profile、委派/父子运行标识、状态、阶段、结果摘要、结构化结果摘要和必要诊断。
- 为 `JsonFileStore` 与 `MemoryStore` 增加委派记录的追加、读取和去重语义；记录不参与普通会话标题、最近活动时间或 `/sessions` 子会话列表。
- 将父级 Subagent 生命周期事件接入异步持久化边界，避免同步文件 I/O 阻塞运行事件循环，并确保排队/启动/终态记录在父会话收尾前得到确定处理。
- 恢复会话时按 `delegation_id` 重构最新记录；非终态记录转换为 `abandoned`/`process_restarted` 的不可恢复结果，不恢复为运行中，也不生成幽灵任务。
- TUI 恢复时把已持久化的委派结果投影为独立的折叠 `SubagentBlock`，保留结果状态与诊断，不把子 transcript 注入普通消息历史。
- 保持旧 JSONL（没有 `subagent` 记录或缺少新字段）可读取、可继续对话；完整子 transcript、跨进程继续执行和子任务搜索仍不在本变更范围内。

## Capabilities

### New Capabilities

- `subagent-run-records`: 定义父会话委派运行记录、追加式存储、结构化结果边界及重启后的 abandoned 恢复语义。

### Modified Capabilities

- `sessions`: 扩展会话 JSONL 记录类型、会话恢复和旧格式兼容要求，使父会话能够读取有界 Subagent 运行记录而不将子会话纳入普通列表。

## Impact

- 影响 `src/codeagent/session/persistence/`、`SessionPersistence`、`AgentSession` 的恢复状态，以及 `src/codeagent/app/tui/` 的历史恢复投影。
- 扩展 `SessionStore` 端口和公开恢复快照字段；既有注入式旧 store 通过能力探测保持兼容。
- 不新增第三方依赖，不改变 core Agent 的工具调用语义，不把 child session 写入用户 SessionStore。
- 新增 session、应用集成和 TUI 恢复回归测试，并更新 v0.5 迭代与架构文档。
