## Why

`src/codeagent/session` 已经按事件、压缩、持久化、运行时和导航做了初步拆分，但会话门面、JSONL 存储和运行控制器仍承载过多职责，部分文件和函数明显超出仓库规模约束。与此同时，异步运行路径直接调用同步文件锁、读写和 `fsync`，可能阻塞事件循环；旧兼容入口也继续扩大模块表面，削弱职责边界。

## What Changes

- 拆分 `AgentSession`、`SessionManager`、运行控制器和 JSONL 存储中的编排、生命周期、提交、索引、分叉及文件操作职责，使生产文件和核心函数回到仓库规定的规模范围。
- 为会话运行时、摘要器、持久化存储、关闭器和策略定义明确的协议类型，移除公共接口中不必要的 `Any`。
- 为同步 JSONL 持久化建立异步安全的调用边界；原子提交、压缩记录和恢复写入不得直接阻塞事件循环，并保持取消、失败回滚和资源释放语义。
- 删除已迁移完成的根级兼容入口，更新生产代码、测试和导出，统一挂载 `events`、`persistence`、`navigation` 和 `runtime` 下的真实模块入口。**BREAKING**
- 保持会话 JSONL 格式、父子链、压缩、分叉、用量、确认和生命周期的既有外部行为不变，并补充结构拆分及异步持久化的回归测试。

## Capabilities

### New Capabilities

<!-- No new user-facing capability is introduced. -->

### Modified Capabilities

- `sessions`: 明确会话运行与持久化调用的非阻塞边界，保持生命周期、恢复、分叉、压缩、用量和确认语义不变。

## Impact

- 受影响代码：`src/codeagent/session/**`、引用旧 session 入口的 `src/codeagent/**` 和 `tests/**`。
- 可能受影响的公共导入路径：根级 `codeagent.session.*` 兼容门面将被移除，调用方需使用职责子包中的真实入口。
- 持久化格式不变，不迁移既有 JSONL 数据，不新增第三方依赖。
- 需要更新 session 相关单元、契约和集成测试，并执行 Ruff、OpenSpec 校验及完整离线测试。
