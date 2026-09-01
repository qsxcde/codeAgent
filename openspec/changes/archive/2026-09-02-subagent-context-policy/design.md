## Context

V5-02 的 `SubagentRequest` 已经包含 `profile` 和不可变的 `context` 字段，但应用层只生成 `read_only` 请求，`DelegateTool` 也没有公开上下文参数。子 Session 工厂目前按一个固定集合过滤工具，且没有把角色意图注入模型系统提示；父历史隔离已经成立，因此本变更只需要补齐显式输入和 profile 选择，不应重新设计会话调度。

## Goals / Non-Goals

**Goals:**

- 在 delegate 边界把 profile 和 context 校验成稳定的 provider-neutral 请求。
- 用一个应用层 profile 注册表集中定义角色说明和工具白名单。
- 让 `read_only` 与 `review` 都保持无写入、无 shell、无递归委派的安全边界。
- 将显式 context 作为有界数据渲染到子任务输入，保持父历史和父工具状态隔离。
- 保持省略新参数时的 V5-02 行为兼容，并为拒绝路径补充离线回归测试。

**Non-Goals:**

- 不在本变更实现预算、墙钟超时、并发调度、事件模型或持久化。
- 不新增写入型、shell 型或网络型 Subagent profile。
- 不把任意父消息、完整 transcript、工具对象或 SessionManager 引用复制给子 Agent。
- 不修改 core 的 Subagent 契约形状；它已有的 `SubagentContextItem` 作为本阶段的边界类型。

## Decisions

### 1. 在组合根集中维护 Profile 规格

在 `app/composition/subagent/profiles.py` 中用不可变 profile 规格映射名称、角色指令和工具白名单。`read_only` 的指令强调探索和事实核验，`review` 的指令强调发现问题、风险和证据；两者暂时共享 `read`、`grep`、`find`、`ls`、`skill` 白名单。未知 profile 在 delegate 和 runner 两层都失败关闭。

相比只在 system prompt 中描述“不要写入”，集中白名单能在模型请求前阻止能力泄漏；相比为每个 profile 分散写条件，注册表更容易审计和扩展。

### 2. 在 DelegateTool 边界解析并限制上下文

`DelegateTool` 将 JSON 参数中的 context 数组转换为 `SubagentContextItem`。每项只接受 `kind`、`content` 和可选 `source`，拒绝未知字段、空文本和错误类型；本阶段固定最多 8 项、单项最多 2,000 字符、总计最多 8,000 字符。超限在创建 `SubagentRequest` 前返回 `invalid_request`，因此不会分配子 Session 或模型。

参数 schema 提供模型可见的结构提示，Python 校验负责真正的安全边界。省略 context 映射为空元组，保持现有只传 task 的调用语义。

### 3. 用独立渲染器构造子输入

新增应用层 context 渲染辅助，将 profile 角色指令留在系统提示，将 task 和 context 项作为用户可见输入分段渲染。上下文区块明确标注为“供分析的数据”，并展示 kind/source；不把它拼接到父 Session 的 history，也不传递父模型消息。渲染前再次使用同一边界常量，避免未来绕过 DelegateTool 直接构造请求时生成无界输入。

### 4. 通过 Session 装配参数注入角色提示

为组合根的 Agent 配置/Session 工厂增加可选的 profile instruction 参数，仅子 Session 工厂传入；根 Agent 保持现有系统提示。角色指令以附加系统提示形式进入 `ChatModelPort`，不能被 context 文本覆盖。子 Session 仍使用 `enable_subagents=False` 和 profile 白名单，父 Session 的 store、runner 和可变历史不变。

### 5. 保持旧入口和错误可消费

`profile` 缺省仍为 `read_only`，`context` 缺省为空；没有 runner 的直接 `create_agent_config` 仍不注入 delegate。参数错误映射为现有 `ToolResult` 错误结构并携带 `invalid_request` 或 `permission_denied`，让父 Agent 可继续下一轮。Profile 的工具列表测试和 FakeClient 请求体测试同时锁定模型看到的实际能力。

## Risks / Trade-offs

- [Context injection] 显式上下文可能包含诱导性指令 → 以系统层 profile 约束和“数据区块”标记隔离；工具白名单是硬边界，不依赖模型自律。
- [Profile drift] 角色描述与工具白名单可能未来不一致 → 由单一 profile 规格同时提供 prompt 和 allow-list，并用每个 profile 的组合测试验证。
- [Context limits] 固定字符上限不是 token 上限 → 本阶段优先保证可预测的输入边界；准确 token/预算治理交由 V5-04。
- [Review capability] `review` 暂时只能读取，不能自动修复 → 这是有意的安全取舍，写入 profile 需另行设计确认和资源边界。

## Migration Plan

1. 先补充 delegate/profile/context 的失败优先测试，再实现解析、profile 规格和子输入渲染。
2. 更新组合根调用和 V5.0 迭代文档，运行窄测试、分层测试、Ruff、OpenSpec 与完整离线测试。
3. 若回滚，只需移除 profile instruction/context 参数并恢复固定 `read_only` 白名单；旧的 task-only 委派协议无需数据迁移。
