## 1. 纯函数:估算 / 切点 / 文件操作(session/compaction.py,先行)

- [x] 1.1 `session/compaction.py`(新):`estimate_tokens(message) -> int`(字符/4 保守高估;content + tool_calls(name + json args);工具输出 content 计入)
- [x] 1.2 `find_cut_point(messages, budget=20_000) -> int`:从最新往回按完整轮次打包累积,只切 user 消息,软预算;全保留(0)语义
- [x] 1.3 `extract_file_ops(messages) -> dict{readFiles, modifiedFiles}`:从 tool_calls 提取 read/write/edit 的 file_path(read → readFiles;write/edit → modifiedFiles)
- [x] 1.4 测试(`tests/session/test_compaction.py` 新):估算(含工具参数/输出大头)、切点(轮次边界/预算软目标/全保留)、文件操作提取、空消息边界

## 2. store:compaction entry 语义 + 上下文重构

- [x] 2.1 `store.py`:`append_compaction` 修正——entry 生成 `id`(uuid7)/`parentId`(调用方传入,当前叶子)/`firstKeptEntryId`/`summary`/`details`;`CompactionEntry` 增 `first_kept_entry_id` 字段;两后端一致
- [x] 2.2 `store.load_context(session_id) -> (summary | None, list[Message])`:取最新 compaction 的 summary + `firstKeptEntryId` 起消息(旧压缩记录/被压缩消息物理保留但不出现在上下文);无压缩记录时返回 (None, 全量)
- [x] 2.3 测试(`tests/session/test_store.py` 增量):entry 字段完整、两后端一致、二次压缩后 load_context 只认最新边界、全量 load_messages 仍含被压缩消息

## 3. Summarizer 端口与装配

- [x] 3.1 `core/ports.py`:增 `Summarizer` 协议(`summarize(messages: list[Message], prev_summary: str | None) -> str`)
- [x] 3.2 `app/container.py`:`create_agent_session` / `create_session_manager` 增 `summarizer` 参数(缺省 None = 压缩不可用,保持既有调用兼容);组合根装配(真实实现经 create_llm 通道;测试注入桩)
- [x] 3.3 测试(`tests/test_container.py` 增量):注入桩 Summarizer 的会话可压缩;未注入时 compact() 明确报错

## 4. session:压缩 / 触发 / 摘要注入

- [x] 4.1 `session/session.py`:`compact() -> bool` 公开方法(异步)——估算切点 → Summarizer 摘要(注入桩离线可测)→ append_compaction(entry id 记入 `_summary_entry_id`)→ 内存历史截断为保留消息;Summarizer 缺失时明确报错
- [x] 4.2 摘要注入:session 持 `_summary`;`run()` 首部插入虚拟 user 消息(`SUMMARY_PREFIX` 包裹,id=`summary-<entry_id>`,parent_id=entry id);结束后过滤 `summary-` 前缀消息再更新历史与落盘
- [x] 4.3 阈值触发:session 记录最近 `usage.input_tokens`;`run()` 的 `turn_end` 后检查 `> context_window - 16_384`(context_window 经注入,缺省 128_000)自动 compact();新 user 消息 parent_id = `_summary_entry_id`(压缩后)
- [x] 4.4 测试(`tests/session/test_session.py` 增量):手动压缩(摘要/截断/entry 落盘/虚拟消息不落盘)、压缩后继续对话 parent 链、阈值触发(注入 context_window 小值)、二次压缩增量(桩摘要拼接)、Summarizer 缺失报错

## 5. ModelSpec context_window

- [x] 5.1 `ai/catalog/spec.py`:`ModelSpec` 增 `context_window: int | None = None`;`builtin.py` 目录补充各模型上下文窗口(deepseek-v4-flash 等)
- [x] 5.2 测试(`tests/ai/test_model_store.py` 增量):context_window 字段透传、缺省 None

## 6. TUI /compact 接线

- [x] 6.1 `commands.py` 注册 `/compact`(summary「压缩当前会话上下文」);`view.py` 分派 → `manager.current.compact()`;反馈压缩结果;无会话/未注入 Summarizer 就地提示
- [x] 6.2 测试(`tests/tui/test_commands.py` / `test_view.py` 增量):/compact 解析与分派、反馈、错误路径

## 7. 收尾

- [x] 7.1 全量离线测试全绿;`openspec validate --change session-compaction` 通过
- [x] 7.2 文档同步:v0.2.md T-37 状态与 E 记录
