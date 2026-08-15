## Context

- 现状:`CompactionEntry(summary, details{readFiles, modifiedFiles}, parent_id)` 已在 store 预留(2026-08-14);`EventType.USAGE` 事件带 `{input_tokens, output_tokens, reasoning_tokens}`;会话 `run()` 全异步、`turn_end` 后落盘本轮消息;`ModelSpec` 无 `context_window`;消息模型:user/assistant/tool 三类(无 image、工具结果 = tool 消息 content、assistant 带 `tool_calls`);`core/ports.py` 已有端口模式(ApprovalPolicy 先例)。
- 约束:append-only 不破(压缩 = 追加 entry,物理历史保留);离线可测(估算/切点/文件操作提取为纯函数,Summarizer 注入桩);分层(session 不 import ai/tools;Summarizer 端口在 core,实现在组合根);事件契约不变(压缩经既有事件感知)。
- 语义对齐 Pi(`core/compaction/` + `session-manager.ts`,2026-08-15 源码实查):阈值触发 `contextTokens > contextWindow - reserve(16k)`;切点预算 `keepRecentTokens(20k)`;摘要 = 包裹标记的注入消息;`appendCompaction` = "child of current leaf, then advance leaf"(新消息父 = 压缩记录)。动机见 proposal.md;行为契约见 specs(sessions / tui delta)。

## Goals / Non-Goals

**Goals:**
- 手动 `/compact` + 阈值自动压缩;压缩后上下文 = 摘要 + 保留消息,语义不丢(回归测试)。
- parentId 链正确接回压缩记录;二次压缩增量合并;物理历史完整保留。

**Non-Goals:**
- 溢出恢复通道(Pi 的 overflow 触发:模型报 context 超限后压缩重试——需模型错误分类,后续);
- split-turn 前缀摘要(切点只选 user 消息,MVP 简化);
- 压缩进度事件/后台异步压缩(同步压缩,MVP);
- 压缩撤销(压缩记录不可逆;物理历史可回放但上下文不回退)。

## Decisions

1. **Token 估算(纯函数)**:`estimate_tokens(message) = max(1, chars // 4)`;chars = content 长度 + 各 tool_call 的 `name + json.dumps(args)`(工具参数计入);tool 消息的 content(工具输出)是主要大头(如 bash 30k 字符 ≈ 7500 tokens)。无 image 分支(与 Pi 差异);保守高估对齐 Pi。
2. **切点算法(只切 user,软预算)**:
   ```
   find_cut_point(messages, budget=20_000) -> int(首个保留索引):
     从最新往回按完整轮次打包累积(一轮 = 一个 user + 其后所有消息);
     若加入更早一轮会超预算且已累积 > 0 → 切;
     返回必为 user 消息索引;全保留(切点 0)→ 不压缩。
   ```
   不拆 turn 的取舍:预算为软目标(一轮超预算整轮保留,reserveTokens 余量兜底);换来摘要边界 = 完整轮次(上下文一致性易测)与免 TURN_PREFIX 摘要变体。
3. **Summarizer 端口**:`core/ports.py` 增 `Summarizer` 协议 `summarize(messages: list[Message], prev_summary: str | None) -> str`;实现注入(组合根接 `create_llm` 通道,离线测试注入桩/脚本化 FakeClient);摘要窗口 = 上次压缩边界 → 切点;第二次压缩 `prev_summary` 传入,桩实现做拼接合并,真实实现提示词要求"保留既有信息 + 合并新窗口"(对齐 Pi UPDATE_SUMMARIZATION_PROMPT 语义,但合并策略在实现内,MVP 不强约束格式)。
4. **compaction entry 语义(照搬 Pi append-as-child-of-leaf)**:
   - `store.append_compaction` 修正:entry 生成 `id`(uuid7)、`parentId` = 当前历史最后一条消息 id、`firstKeptEntryId` = 切点消息 id、`summary`、`details{readFiles, modifiedFiles}`、`timestamp`;
   - 会话压缩后 `_summary_entry_id` 记录 entry id;后续 run 的新 user 消息 `parent_id = _summary_entry_id`(摘要成为新对话的根);
   - 二次压缩:新 entry `parentId` = 旧 entry id(摘要链:`compaction1 → compaction2 → new_user`)。
5. **摘要注入上下文(不落盘)**:压缩后会话持有 `_summary`;每次 `run()` 在 history 首部插入虚拟消息 `Message(role="user", content=SUMMARY_PREFIX + summary, id="summary-<entry_id>", parent_id=_summary_entry_id)`;run_turn 正常处理;结束后 session 过滤 `summary-` 前缀消息再更新 `_history` 与落盘(compaction entry 已落盘,防重复);前缀标记让模型识别"历史摘要"。
6. **上下文重构(读侧)**:`store.load_context(session_id) -> (summary | None, list[Message])`:扫描 entries,取**最新** compaction entry 的 summary 与 `firstKeptEntryId`,返回 summary + 该 id 起消息;旧 compaction/被压缩消息物理保留,不出现在上下文(只认最新压缩边界);会话启动时若 store 有压缩记录则加载 summary(恢复压缩状态)。
7. **触发**:
   - 手动:`session.compact()` 公开方法(异步;内部走 4/5/6);`/compact` 命令接线;
   - 阈值:session 记录最近一次 `usage.input_tokens`(每轮调用后更新);`run()` 的 `turn_end` 后检查 `input_tokens > context_window - 16_384`(context_window 取 ModelSpec,缺省 128_000)时自动 `compact()`(同步 await,完成后本轮正常结束);
   - `ModelSpec` 增 `context_window: int | None`;`builtin.py` 目录补充(deepseek-v4-flash/pro 等);未知模型缺省兜底。
8. **文件操作跟踪**:`extract_file_ops(messages) -> {readFiles, modifiedFiles}` 纯函数——从被摘要消息的 tool_calls 提取 read/write/edit 的 `file_path`(read → readFiles;write/edit → modifiedFiles)+ 上次 compaction details 累积;进 `CompactionEntry.details`(对齐 Pi CompactionDetails)。
9. **事件**:压缩不新增事件类型;`/compact` 反馈经 `append_info`(TUI);自动压缩过程用户可见性 MVP 从简(压缩前后各轮次正常 emit)。

## Risks / Trade-offs

- [摘要丢失语义] → 摘要窗口 = 完整轮次 + 保留精确路径/函数名/错误消息的提示词约束 + 二次压缩增量合并;回归测试锁定压缩前后行为一致性(注入桩摘要可断言)。
- [阈值误触发(小窗口模型/大输出)] → reserveTokens 余量 + 只切完整轮次 + 切点 0 不压缩;context_window 目录值校准。
- [压缩后继续对话的链断裂] → parent_id 接回 entry(决策 4)+ store 重载恢复摘要状态(决策 6);回归测试断言链完整。
- [虚拟摘要消息污染历史] → 标记 id 过滤(决策 5);测试断言 store 无 `summary-` 消息。
- [同步压缩阻塞下一轮] → LLM 摘要调用耗时;MVP 接受(手动挡场景少),异步压缩留后续。

## Migration Plan

纯增量,无部署;`append_compaction` 语义修正(旧调用方仅测试用,无存量数据)。实现顺序:纯函数(估算/切点/文件操作)→ store entry 语义 + load_context → Summarizer 端口 + 装配 → session 压缩/触发/注入 → /compact 接线 → 测试收尾。

## Open Questions

无(切点粒度/同步触发/增量合并/context_window 兜底四项已在探索阶段定案;溢出恢复与 split-turn 明确移出)。
