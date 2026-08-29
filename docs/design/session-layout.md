# Session 模块布局与迁移说明

`codeagent.session` 仍保留 `AgentSession`、`SessionManager` 和 `EventBus` 这三个包级稳定导出；实现按职责归并到子包。新代码不得依赖已删除的根级兼容模块。

## 规范入口

| 能力 | 规范入口 |
|---|---|
| 事件总线 | `codeagent.session.events` |
| 持久化协议、记录、内存后端和提交协调 | `codeagent.session.persistence` |
| JSONL 文件后端 | `codeagent.session.persistence.jsonl` |
| 会话树和分支导航 | `codeagent.session.navigation` |
| 运行控制、状态、确认和事件映射 | `codeagent.session.runtime` |
| 压缩 | `codeagent.session.compaction` |
| 会话壳和生命周期管理 | `codeagent.session`、`codeagent.session.session`、`codeagent.session.manager` |

持久化后端的同步文件访问、锁、索引更新和 `fsync` 由 `SessionPersistence` 的异步边界在线程中执行。异步会话运行路径应使用 `commit_turn_async()` 和 `append_compaction_async()`；同步 `commit_turn()` 仅供同步调用方使用。

## Breaking change：已删除入口

以下旧路径不再导出兼容门面，调用方必须迁移：

| 旧路径 | 替代入口 |
|---|---|
| `codeagent.session.bus` | `codeagent.session.events` |
| `codeagent.session.store` | `codeagent.session.persistence` |
| `codeagent.session.memory_store` | `codeagent.session.persistence.memory_store` |
| `codeagent.session.json_file_store` | `codeagent.session.persistence.jsonl` |
| `codeagent.session.persistence.jsonl_store` | `codeagent.session.persistence.jsonl` |
| `codeagent.session.persistence.jsonl_reading` | `codeagent.session.persistence.jsonl.reading` |
| `codeagent.session.persistence.jsonl_writing` | `codeagent.session.persistence.jsonl.writing` |
| `codeagent.session.persistence.jsonl_indexing` | `codeagent.session.persistence.jsonl.indexing` |
| `codeagent.session.persistence.jsonl_forking` | `codeagent.session.persistence.jsonl.forking` |
| `codeagent.session.store_codec` | `codeagent.session.persistence.codec` |
| `codeagent.session.store_index` | `codeagent.session.persistence.index` |
| `codeagent.session.store_models` | `codeagent.session.persistence.models` |
| `codeagent.session.tree` | `codeagent.session.navigation` |
| `codeagent.session.session_runtime` | `codeagent.session.runtime` |

这是有意的 breaking change：旧路径导入失败，避免新增代码继续绕过职责边界。迁移后请优先从子包导入公开对象，例如 `from codeagent.session.persistence import JsonFileStore`。
