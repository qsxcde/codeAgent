## Context

当前会话已经有手动压缩、基于最近一次 provider usage 的自动阈值压缩、完整 user turn 截断、增量摘要链和异步 JSONL 持久化。自动触发仍由固定保留量和 `_last_input_tokens` 驱动,而预算模块已经能够估算 system prompt、工具定义、普通历史、工具结果、输出预留和有效输入余量。请求前 preflight 当前只做判定,明确不负责压缩。

本设计遵循现有会话 JSONL append-only、摘要不作为普通消息落盘、core 不依赖 session/ai/tools/config 具体实现、同步文件 I/O 不进入事件循环等约束。详细行为契约见本 change 的 `specs/` 增量规格。

## Goals / Non-Goals

**Goals:**

- 让自动压缩基于下一次请求的有效输入预算触发,并在不同模型窗口间保持一致语义。
- 让压缩目标、完整轮次边界、候选预算验证、并发协调和失败语义可测试且可诊断。
- 保持已提交对话轮次、累计 usage、物理历史和压缩链的一致性。
- 让 TUI 能区分自动压缩的进行中、成功、跳过、失败和取消状态。

**Non-Goals:**

- 不在本 change 中实现长期记忆、语义检索、自动模型路由或多 Agent 上下文共享。
- 不把压缩逻辑放进 `core.context.preflight`,也不让 core 直接访问 provider、工具实例或会话存储。
- 不删除或重写既有 JSONL 历史,不改变现有分叉和恢复的物理格式。
- 不通过自动重试掩盖单个超大 turn 或摘要本身超预算的问题。

## Decisions

### 1. 以“下一次请求预算”作为唯一触发事实

每次成功提交后,由组合层使用当前模型选择、系统提示、工具定义、摘要和已提交消息构造下一次请求的 `ContextBudgetInput`,生成预算快照交给 session。session 不读取 provider 的具体 usage 字段来推断下一次上下文大小；实际 usage 只作为诊断和累计用量来源。

有效输入预算定义为:

```text
input_budget = context_window - output_reserve_tokens - reserve_tokens
```

自动策略使用可配置的比例阈值与绝对余量阈值。默认可从 `trigger_ratio = 0.80`、`target_ratio = 0.65` 和 `trigger_headroom_tokens = 2048` 起步；触发后目标必须低于触发边界。比例阈值解决不同窗口模型的一致性,绝对余量用于小窗口和估算误差保护。阈值非法时在配置阶段报错。

替代方案是继续使用 `last_input_tokens > context_window - fixed_reserve`；该方案无法覆盖工具结果、系统提示和 provider 缺少 usage 的情况,也无法随输出预留和模型切换正确调整,因此不采用。

### 2. 将压缩实现为“计划 → 摘要 → 验证 → 持久化”流水线

`session/compaction/policy.py` 负责根据预算和历史产生不可变的压缩计划,包含摘要窗口、保留窗口、触发原因、目标预算和结构化跳过原因。计划必须在 user 消息起始处截断,保留配置要求的最近完整轮次,并在没有安全边界或单轮过大时明确返回 `no_safe_boundary` / `oversized_turn`。

`session/compaction/service.py` 负责执行计划并生成增量摘要。摘要输入继续包含既有摘要,同时明确要求保留未完成任务、决策、文件路径、修改记录、函数名、工具错误和必要的工具结果语义。摘要与保留消息形成候选上下文后,使用与请求预算相同的估算口径重新验证；候选超过目标时不追加 entry,返回 `summary_too_large` 或其它结构化结果。

替代方案是先截断并直接写入摘要 entry,再依赖下一次 preflight 发现仍然超限；该方案会把不可用的压缩状态持久化,不采用。

### 3. 持久化成功后才发布压缩后的内存状态

压缩 entry 通过现有异步持久化边界追加。只有 append 成功且结果确定后,才原子地更新 summary、summary entry id、details 和运行期 history。持久化失败或结果不确定时,保留原内存上下文并发布对应诊断，避免内存状态与 JSONL 真相源分叉。

自动压缩发生在本轮对话成功提交之后,但压缩属于提交后的独立后处理。`run_coordinator` 必须保留“对话轮次 completed”的结果,另行记录 `compaction_failed`、`compaction_cancelled` 或 `persistence_uncertain`，不能因为压缩失败而让已经落盘的消息看起来像未完成。

### 4. 使用单飞门和上下文指纹实现滞后与幂等

session compaction runtime 持有一个压缩 gate。手动和自动入口都必须在 gate 内重新读取当前 history、summary 和预算；后获得 gate 的入口如果发现上下文已低于触发阈值,直接返回 skipped/no-op。成功压缩后记录上下文 fingerprint 和前后预算，避免同一上下文重复压缩。

失败后不进行无界自动重试；记录失败原因和短暂 cooldown，下一次显式运行或新的上下文变化可以再次尝试。模型切换、消息追加或工具结果变化会产生新的 fingerprint，并按新模型窗口重新判断。

替代方案是只依赖 `SessionRunCoordinator` 的调用顺序而不设置 session 级协调；该方案无法保护手动命令、恢复和自动触发之间的并发交错，不采用。

### 5. 复用现有事件流而不是新增生命周期体系

继续使用 `COMPACTION_STARTED` 和 `COMPACTION_FINISHED`，但扩展 metadata：

- `trigger`: `manual` 或 `auto`
- `reason`、`reason_code`
- `before_estimate`、`after_estimate`、`input_budget`、`target_budget`
- `summarized_turns`、`kept_turns`
- `status`: `compacted`、`skipped`、`failed`、`cancelled`
- `summary_entry_id` 和必要的 persistence 诊断

TUI 继续把压缩映射为 `compacting` 阶段，普通提交在此期间被阻止但草稿保留。这样既兼容已有 `/compact` 状态，也让自动压缩和手动压缩共享渲染、测试和收尾语义。

### 6. 保持配置兼容并逐步替换固定目标

保留现有显式 `compact_budget` 参数作为兼容性覆盖：调用方明确设置时可作为目标预算上限参与策略；未设置时使用有效输入预算比例目标，不再默认把所有模型压到固定 20,000 tokens。新的自动策略配置集中表达触发比例、目标比例、绝对余量和最少保留轮次，并由组合根校验后注入 session。

## Risks / Trade-offs

- **[摘要质量不稳定]** → 保留结构化文件操作详情和关键错误字段；对候选摘要执行预算验证，并增加固定摘要输入/输出的回归测试。
- **[估算口径与 provider 实际 token 不同]** → 所有触发和候选验证复用同一本地预算估算；保留 estimate/uncertain 来源标记，不把本地估算伪装成实际 usage。
- **[单个工具结果或 turn 大于整个窗口]** → 返回 `oversized_turn`，由后续工具结果治理处理；自动压缩不拆轮次、不无限重试。
- **[压缩持久化耗时影响交互]** → 摘要调用保持异步，文件写入继续走异步持久化边界；TUI 明确展示 compacting 阶段并保存草稿。
- **[提交后压缩失败导致用户误解]** → 将本轮 completed 与压缩后处理状态分开发布，状态栏和诊断显示具体 compaction 状态。
- **[模型切换后阈值变化造成频繁压缩]** → fingerprint 包含模型窗口和输出预留，使用触发/目标滞后区间重新计算，不沿用旧模型阈值。
- **[手动入口与自动入口竞态]** → 所有入口经过同一个单飞 gate，并在获得 gate 后重新检查，保证只追加一个有效压缩 entry。

## Migration Plan

1. 先实现预算快照消费、策略配置和压缩计划，但保留现有手动 `/compact` 入口及 JSONL entry 格式。
2. 将自动触发切换到新策略默认值；旧的显式 `compact_budget` 继续生效，未配置者采用比例目标。
3. 补充事件/TUI 诊断、失败收尾、恢复、分叉和模型切换回归测试，再运行完整测试、Ruff、OpenSpec 验证和构建检查。
4. 如需回滚，可关闭自动策略或恢复固定目标配置；既有压缩 entry、物理历史和摘要链无需迁移，旧版本仍可读取。
