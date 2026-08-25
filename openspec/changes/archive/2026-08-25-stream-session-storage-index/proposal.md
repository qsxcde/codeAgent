## Why

`JsonFileStore` 当前通过 `read_text().splitlines()` 读取整个 JSONL 会话文件，并在恢复和分叉时继续构造完整的 entry/message 列表。长会话会产生不必要的内存峰值和重复 I/O，`/sessions` 列表、用量读取和会话切换也会反复扫描已经稳定的历史文件。

P1-1 需要在不改变 JSONL 作为真实数据源、不改变会话恢复语义的前提下，降低长会话的读取成本，并让常用元数据查询可以复用轻量缓存。

## What Changes

- 将文件后端的内部 JSONL 解析改为真正逐行读取，保持空行跳过、坏 JSON 行容错和 header/version 校验语义。
- 增加会话目录级的轻量索引缓存，记录标题、模型配置、用量聚合、最近压缩切点和源文件指纹。
- 以 JSONL 文件为唯一真实数据源；索引缺失、损坏、过期或更新失败时，自动从 JSONL 流式重建，不阻塞会话读写。
- 让 `list`、`get`、`load_usage` 优先使用有效索引，减少重复扫描历史正文。
- 让 `load_context` 只保留需要恢复到模型上下文的消息，让 `fork` 采用逐行扫描和逐行写入，避免构造完整历史副本和待写行列表。
- 保持 `SessionStore` 公共协议、JSONL append-only 格式、`MemoryStore` 行为、压缩语义和分叉语义兼容。
- 不引入数据库迁移、RAG、完整逐消息随机访问索引，也不因“最后更新时间”需求修改每条 entry 的格式；初版更新时间使用源文件指纹/文件修改时间表示。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `sessions`: 会话文件读取、元数据查询、上下文恢复和分叉增加流式处理及可重建索引要求，同时保持现有持久化和恢复契约。

## Impact

- 主要影响 `src/codeagent/session/store.py` 及 `tests/session/test_store.py`。
- 可能新增 session 层内部的索引数据结构或辅助模块；不改变 `core`、`SessionManager` 和 `AgentSession` 的公共接口。
- 会话目录新增私有索引文件，索引文件需要遵循现有会话目录/文件权限策略。
- 不新增第三方依赖；JSONL 文件仍可被诊断、备份和删除，索引可随时重建。
