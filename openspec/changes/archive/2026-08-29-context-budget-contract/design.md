## Context

当前 `core` 只接收 `Message` 列表和工具对象,`ChatModelPort` 在组合根内另外注入 system prompt 并把工具对象序列化为 provider 工具定义;因此一次真实请求的组成没有统一的描述入口。会话侧已有 `context_window`、本轮 provider input tokens 和累计 usage,但它们分别服务于压缩、事件和持久化,不能直接作为同一份预算状态使用。模型目录的 `ModelSpec` 已有上下文窗口字段,用户 `models.json` 的解析却没有完整保留该字段。

实现必须维持既有依赖方向:预算值对象和端口放在 `core`,不能导入 `ai`、`session`、`tools` 或配置;模型目录和 provider 序列化留在 `ai`/组合根;会话只负责运行期状态与已提交用量边界。详见 `proposal.md` 和本变更的 delta specs。

## Goals / Non-Goals

**Goals:**

- 建立不可变、provider 无关的请求预算值对象,以统一口径描述窗口、输出预留、保留余量和互斥的输入组成。
- 让组合根能够把 system prompt、工具定义、模型窗口元数据和 core 消息组成装配成同一份预算快照,并携带估算来源/不确定性。
- 为 core 上下文准备扩展增加预算感知能力,同时保留现有只接收消息列表的转换器。
- 在 session 中隔离最近一次估算、最近一次实际 usage 与成功提交后的累计 usage,为后续请求前检查和压缩提供稳定输入。
- 补齐自定义模型目录的上下文窗口解析,并用离线测试锁定窗口来源和模型切换行为。

**Non-Goals:**

- 本变更不实现自动压缩、工具结果截断、MCP/Skill 注入、预算超限时的具体恢复策略或 TUI/CLI 展示。
- 本变更不引入 provider 专属 tokenizer,也不承诺本地字符估算与 provider 实际 token 完全一致;不确定性必须可见。
- 本变更不改变 JSONL 历史消息、父级链、压缩记录格式和已有 usage entry 的提交语义。

## Decisions

### 1. 在 core 定义中立的预算值对象,由组合根提供请求组成

在 `core` 增加独立的预算模块和值对象,建议包含以下语义字段:

- `ContextBudgetInput` 或等价请求描述:模型窗口、输出预留、保留余量、system prompt、工具定义、普通历史、工具结果及估算器来源;
- `ContextBudgetSnapshot` 或等价结果:各组成估算、总输入估算、可用输入预算、余量、状态(`estimate`/`uncertain` 等)和窗口来源;
- 独立的 `ActualUsage`/`CommittedUsage` 形态用于表达 provider 实际值与会话累计值,不复用预算快照中的估算字段。

这些对象只携带字符串、消息、中立工具定义摘要和数字,不携带 provider client、session store 或具体工具类。对象应尽量不可变,计算函数保持纯函数,使重复计算和边界测试不产生副作用。

备选方案是把预算字典直接加到 `ModelPort.generate()` 参数中,或让 session 负责计算所有字段。前者会把请求组成和兼容适配逻辑散落在循环调用点,后者会迫使 session 了解组合根的 system prompt/工具序列化;两者都违反职责边界,因此不采用。

### 2. 在模型适配边界生成真实请求组成,core 只消费中立视图

保留 `ModelPort.generate(messages, tools)` 的现有最小调用面,并通过可选的预算描述/上下文准备端口或适配器能力把以下信息提供给 runtime:

1. core 消息按当前临时上下文计算普通历史与 tool result 估算;
2. 组合根把 `ChatModelPort` 实际会前置的 system prompt 和实际序列化的工具定义转换为中立描述;
3. 模型目录解析结果提供 `context_window` 与最大输出限制,由组合根计算有效窗口与来源;
4. runtime 在调用旧式 `transform_context` 前后使用同一个请求描述,只把最终临时视图提交给模型,不回写 session 历史。

这样预算统计的是“将要发送给 provider 的请求形状”,而不是仅统计 core 消息。若某个旧模型端口无法描述 system prompt 或工具定义,适配器必须将缺失标记为 uncertain,不能把不完整估算宣称为精确值。

### 3. 用统一的估算器和互斥分组避免重复计算

所有组成项使用当前已有 token 估算策略的统一封装,并将消息分为普通对话历史与工具结果两个互斥分组。工具调用参数、工具结果内容、system prompt 和工具 schema 均通过同一估算口径计数;工具定义为空时为零。总输入估算为各组成项之和,可用输入预算为窗口扣除输出预留和显式保留余量后的结果。

不在本变更中追求 provider tokenizer 精确模拟。估算器应返回来源/精度标志,并保留足够信息供后续变更决定是拒绝请求、压缩、截断还是继续请求。

### 4. 将 estimate、actual、committed 分成不同生命周期

请求开始时由 session/runtime 写入运行期的最新预算快照;provider 返回时记录本轮实际 usage;只有消息和 usage 成功提交后,才更新累计 usage。已有持久化 usage entry 仍是累计值的权威来源,预算快照不新增历史 entry,也不重命名已有 `last_context_tokens` 的兼容读取语义。

备选方案是让实际 input tokens 覆盖预算估算字段,但这会丢失请求前诊断信息,并使取消/失败轮次很难解释。因此采用“同一运行内并列保存、提交后才累计”的生命周期模型。

### 5. 窗口元数据采用显式来源和保守兜底

扩展 `models.json` 解析以识别 `contextWindow` 和 `context_window`,校验为正整数并保留到 `ModelSpec`;模型解析优先使用最终选中的用户覆盖/目录值,缺失时使用现有默认窗口但标记来源为 fallback/uncertain。模型切换只替换下一请求的有效元数据,不重算或改写历史消息和既有 usage。

这比在每个 provider 工厂内硬编码窗口更可追溯,也避免自定义模型落入“使用默认值但看起来像精确值”的隐性错误。

### 6. 以兼容适配保留现有上下文转换器

不直接删除 `TransformContext = Callable[[list[Message]], ...]`。每次请求先在隔离的消息副本上执行旧转换器,再把结果传给预算感知入口;两者可以组合而不是互相绕过。预算信息通过中立对象传入新入口,工具只暴露不可共享的名称、描述和参数 schema。这样现有 core 测试和外部调用方可以逐步迁移,而新的扩展不会被迫导入 session 或 provider 类型。

### 7. 对不确定窗口采用显式策略

旧模型适配器无法描述有效上下文窗口时,core 仍生成带 `fallback`/`uncertain` 标记的预算快照。`AgentLoopConfig.uncertain_budget_policy` 明确决定扩展是否继续:默认 `allow` 保持旧适配器可用,需要严格边界的组合根可设置为 `fail`,此时在调用扩展或模型前以结构化 `context_preparation_failed` 结束。无论策略如何,不确定性都不能被伪装成精确估算。

## Risks / Trade-offs

- **[估算值与 provider 实际 token 不一致]** → 明确标记估算来源与 uncertain 状态,保留输出预留和保留余量,把精确 tokenizer/超限处理留给后续变更。
- **[system prompt 或工具 schema 漏统计]** → 在组合根适配器处建立请求组成快照,增加包含 system prompt、工具 schema 和工具结果的端到端离线测试。
- **[旧转换器与新预算入口语义分叉]** → 旧入口统一通过适配器执行,对同一份临时消息视图测试调用顺序和持久化历史不变。
- **[模型切换后沿用旧窗口]** → 每次请求从当前最终模型选择结果重新解析窗口,并增加大小窗口切换与恢复测试。
- **[失败轮次污染累计用量]** → 仅在 session 提交边界之后聚合 committed usage;失败/取消测试验证累计值和 usage entry 均不变化。
- **[预算模块扩大 core 体积]** → 将预算值对象与计算函数放入独立模块,保持纯数据/纯计算,不把 provider、压缩、UI 或工具治理逻辑塞入 core。

## Migration Plan

1. 先增加 core 中立预算类型、估算器和可选预算感知端口,并用旧 `transform_context` 适配器保持现有调用路径。
2. 在模型目录和组合根补齐上下文窗口读取、来源标记、请求组成描述和模型适配测试。
3. 在 session 中接入运行期预算快照和 actual/committed usage 分离,确保现有 JSONL 读取与写入兼容。
4. 运行预算相关窄测试、边界/导入测试和 OpenSpec 校验;本变更上线后,后续变更再接入请求前阻断、自动压缩、工具结果治理和 TUI 展示。

回滚时删除预算感知入口的装配,保留旧消息列表转换器和已有 usage/JSONL 逻辑;因为本变更不改变历史格式,不需要数据迁移或回滚文件。
