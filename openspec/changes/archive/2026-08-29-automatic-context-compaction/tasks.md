## 1. 预算契约与策略配置

- [x] 1.1 在组合根与 session 配置中增加自动压缩策略配置，支持触发比例、目标比例、绝对余量、最少保留轮次、启用开关和显式 `compact_budget` 兼容覆盖，并校验非法值。
- [x] 1.2 复用并接入 provider-neutral 的上下文预算接口，使 session 能获得包含 system prompt、工具定义、摘要、历史、工具结果、输出预留和安全余量的下一次请求预算快照。
- [x] 1.3 实现基于有效输入预算的触发阈值、目标预算、滞后区间和 estimate/uncertain 来源处理；模型切换后重新计算，不读取累计 usage 作为输入预算。
- [x] 1.4 为预算策略补充单元测试：不同窗口、输出预留、工具结果、缺少 provider usage、非法配置、模型切换和边界相等值。

## 2. 压缩计划与候选验证

- [x] 2.1 重构 `session/compaction/policy.py`，返回包含触发原因、目标预算、摘要窗口、保留窗口和结构化跳过原因的压缩计划。
- [x] 2.2 保证压缩边界只落在完整 user turn 起始，支持最少保留最近轮次，并明确处理 `no_safe_boundary` 与 `oversized_turn`，不进行无界重试。
- [x] 2.3 更新 `session/compaction/service.py`，按计划生成增量摘要，保留任务、决策、文件操作、函数名、工具错误和必要工具结果语义。
- [x] 2.4 使用与请求相同的预算估算口径验证摘要加保留消息的候选上下文；超出目标时返回 `summary_too_large` 等结构化结果且不追加压缩 entry。
- [x] 2.5 保持摘要注入消息、压缩 entry、父级链、物理历史和多次压缩增量合并的兼容行为，并保留显式 `compact_budget` 的兼容语义。
- [x] 2.6 为压缩计划、完整轮次边界、关键内容保留、候选超预算、幂等 no-op 和增量摘要补充单元测试。

## 3. Session 运行时与持久化收尾

- [x] 3.1 在成功提交一轮对话后基于下一次请求预算触发自动压缩，并在下一次模型调用前重新执行预算检查。
- [x] 3.2 在 `compaction_runtime.py` 增加 session 级单飞 gate、上下文 fingerprint 和失败 cooldown；手动与自动入口在 gate 内重新检查最新状态。
- [x] 3.3 保证压缩 entry 经现有异步持久化边界成功且结果确定后才更新 summary、history、details 和 summary entry id。
- [x] 3.4 将已提交对话轮次的 completed 状态与压缩后处理状态解耦，分别处理压缩失败、取消和 persistence uncertain，不重复写入 usage 或回滚已提交消息。
- [x] 3.5 扩展 `COMPACTION_STARTED`/`COMPACTION_FINISHED` metadata，记录 trigger、reason、status、预算前后值、摘要/保留轮次、entry id 和结构化错误。
- [x] 3.6 为自动触发、重复压缩、并发手动/自动入口、持久化失败、取消、恢复、分叉和模型切换补充 session 行为测试。

## 4. TUI 反馈与交互

- [x] 4.1 消费压缩事件并显示自动压缩的 `compacting` 阶段、触发来源、前后预算、摘要/保留轮次和完成状态。
- [x] 4.2 为 skipped、cancelled、failed、persistence uncertain 和 oversized turn 显示明确原因，不将其渲染为成功压缩。
- [x] 4.3 压缩期间阻止冲突的普通提交并保留用户草稿，完成后恢复可提交状态；补充窄终端和事件顺序测试。

## 5. 分层验证与文档

- [x] 5.1 更新现有 compaction、context budget、preflight、session recovery 和 usage 测试的预期，确保预算估算、实际 usage 和累计 usage 仍然隔离。
- [x] 5.2 运行相关 unit/contract/integration/e2e 测试，确认压缩不会在 provider 调用前产生工具副作用，也不会破坏 JSONL 恢复和会话树语义。
- [x] 5.3 更新 v0.4 迭代文档、配置说明和用户可见的 `/compact`/自动压缩行为说明。
- [x] 5.4 运行 `uv run ruff check src tests scripts`、`uv run pytest -q`、`openspec validate --specs`、`openspec validate --changes`、`git diff --check` 和 `uv build`，记录验证结果。
