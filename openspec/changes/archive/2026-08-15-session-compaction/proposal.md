## Why

T-37 上下文压缩(FR-5.6 / F-13):长会话上下文膨胀导致成本与延迟上升。对标 Pi(`earendil-works/pi` 的 `core/compaction/`,2026-08-15 源码实查):阈值 + 溢出双触发、预算回走切点、结构化增量摘要、追加 entry 上下文重构。我们的 JSONL 格式已预留 `compaction` entry(`summary + details{readFiles, modifiedFiles}`),事件契约已有 `usage`(含 input_tokens)——机制缺口:token 统计、`context_window` 字段、Summarizer 端口、切点算法、上下文重构、触发接线。

## What Changes

- **上下文压缩(手动 + 阈值触发)**:
  - 手动:`/compact` 命令强制压缩当前会话;阈值:每轮 `turn_end` 后检查,`最近一次 usage.input_tokens > context_window - 16_384` 时自动压缩(同步,压缩完成后会话继续);
  - `ModelSpec` 增 `context_window` 字段(静态目录补充,缺省兜底 128_000);
- **切点算法(对齐 Pi,适配我们的消息模型)**:从最新往回按**完整轮次**(user 消息 + 其后所有消息)打包累积估算 token(`字符/4`,内容 + 工具参数 + 工具输出),预算 20_000 为软目标;**只切 user 消息**(不拆 turn,MVP 简化,免 split-turn 前缀摘要);全部保留(切点 0)时不压缩;
- **摘要生成(Summarizer 端口)**:`core/ports.py` 增 `Summarizer` 协议(`summarize(messages, prev_summary) -> str`);实现注入(离线测试注入桩,组合根接 LLM);摘要窗口 = 上次压缩边界 → 切点;第二次压缩增量合并(旧摘要 + 新窗口摘要);
- **compaction entry 与 parentId 链(照搬 Pi「append as child of leaf, then advance leaf」)**:entry `id` = 新 uuid7、`parentId` = 当前历史最后一条消息 id、`firstKeptEntryId` = 切点消息 id;压缩后新消息的父 = compaction entry(摘要成为新对话的根);上下文重构 = 最新摘要 + `firstKeptEntryId` 起保留消息;物理历史全部保留(回放/回滚不受影响);
- **摘要注入上下文**:压缩后会话持有摘要;每次 `run` 在历史首部注入一条带标记 id 的虚拟 user 消息(`前缀 + 摘要` 包裹,让模型知道是历史摘要);该消息不落盘(compaction entry 已落盘,防重复);
- **文件操作跟踪**:compaction entry `details{readFiles, modifiedFiles}` 从被摘要消息的工具调用提取 + 上次压缩累积(对齐 Pi `CompactionDetails`);
- 无 **BREAKING**:事件契约不变(压缩过程可经既有事件感知),格式 v1 的 compaction entry 语义落地(原为预留)。

## Capabilities

### New Capabilities

无(均为既有能力的扩展)。

### Modified Capabilities

- `sessions`:新增「上下文压缩」requirement(手动 + 阈值触发、摘要 entry、上下文重构、parentId 链接回、二次压缩增量)。
- `tui`:新增「压缩命令」场景(斜杠命令体系扩展 `/compact`)。

## Impact

- `ai/catalog/spec.py`:`ModelSpec` 增 `context_window: int | None`;`builtin.py` 目录补充各模型上下文窗口;
- `core/ports.py`:增 `Summarizer` 协议(与 `ApprovalPolicy` 同模式,实现注入);
- `session/compaction.py`(新):`estimate_tokens(Message)` / `find_cut_point(messages, budget)`(只切 user)/ `extract_file_ops(messages)`(纯函数,离线可测);
- `session/session.py`:`compact()` 公开方法(手动);`run()` 内 turn_end 后阈值检查 + 自动压缩;`_summary` 状态与虚拟摘要消息注入/过滤;usage 记录(最近 input_tokens);
- `session/store.py`:compaction entry 写侧补 `id` / `parentId` / `firstKeptEntryId`(现 `append_compaction` 的 id 语义修正);读侧重构 `load_context`(摘要 + 保留消息);
- `app/container.py`:装配 Summarizer(离线 FakeClient / 真实 LLM 共用 `create_llm` 通道);
- `app/tui/commands.py` / `view.py`:`/compact` 命令接线;
- `tests/`:`test_compaction.py`(新,纯函数)、`test_session.py`(触发/注入/过滤/链)、`test_store.py`(entry 语义)、`test_container.py`(装配)、`test_view.py`(/compact)。

无 **BREAKING** 变更。
