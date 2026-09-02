## Context

本变更建立在 v0.5 Subagent 串行 MVP 之上。当前应用层已经有临时子 Session、独立上下文、预算和父子事件链路；`profiles.py` 只定义 `read_only` 与 `review`，二者使用相同的 `read`、`grep`、`find`、`ls`、`skill` 工具集合。`delegate_tool.py` 另外硬编码 profile 枚举和 `read_only` 默认值，子 Session 工厂与 TUI 组合路径再分别读取工具白名单和角色指令。

本变更只调整 profile 的能力契约和解析入口，不改变已有 Subagent 生命周期。现有显式 context 校验已经能限制数量、字符数和字段，并在渲染时把 context 标记为数据；这部分作为 Reviewer 的隔离基础继续复用。

## Goals / Non-Goals

**Goals:**

- 建立单一的 profile registry，使 schema、参数校验、角色指令和子工具装配使用同一份定义。
- 将 `explore` 固定为正式的严格只读探索角色。
- 保留 `review` 作为严格只读审查角色，并要求审查范围来自 task、显式 context 或子 Agent 实际读取到的内容。
- 保持最大深度、串行调度、预算、取消、结果回传、事件和持久化语义不变。
- 迁移新的 delegate 调用和测试数据，同时保证历史有界运行记录可以继续读取和展示。

**Non-Goals:**

- 不在本变更中实现 `tester`、测试命令执行或任意进程工具。
- 不新增自动读取 Git diff 的工具；Reviewer 需要的差异或文件范围由父 Agent 通过 task/context 显式提供，专用 diff 工具另行评估。
- 不实现并行调度、DAG、worktree、跨进程恢复或可写 Subagent。
- 不把 profile registry、具体工具名或应用权限策略放入 `core`；core 只传递不透明的 profile 字符串，并将默认请求值同步为正式的 `explore` 名称。
- 不修改 Subagent 状态机、`SubagentResult` 字段、JSONL 记录格式或普通 SessionManager 语义。

## Decisions

### 1. 以 profile registry 作为唯一策略来源

扩展现有 `SubagentProfile` 定义，使每个 profile 同时描述稳定名称、角色指令、允许的工具集合和有限的输出指导。提供 profile 名称枚举和严格查找入口，`delegate` schema、请求解析、runner 校验、子 Session 工厂和 TUI 子 Session 装配都从该入口读取。

这样可以保证“模型看到的 profile”和“实际获得的工具”一致。替代方案是在 `delegate_tool.py`、runner 和两个组合根分别维护枚举及白名单，改动较小但会重新引入 schema 与运行时漂移，因此不采用。

profile registry 继续位于 `app/composition/subagent/`。它是应用层能力策略，不是 provider-neutral 的领域协议；`SubagentRequest.profile` 继续使用字符串，core 不需要知道 `explore` 或 `review` 的产品含义。

### 2. 使用 `explore` 替代 `read_only`，不保留新的输入别名

`explore` 是正式的默认 profile，`review` 保持正式名称。新的 `delegate` schema 只宣传这两个名称，旧的 `read_only` 输入在请求边界被拒绝并返回权限/请求错误。这样可避免长期保留一个职责过于宽泛的兼容入口，也与当前没有已发布外部 Subagent API 的事实一致。

`SubagentRequest` 的默认 profile 字符串同步改为 `explore`，以避免直接构造的合法请求落入已移除的名称；core 不校验、枚举或解释 profile，实际 profile registry 仍由应用组合层负责。

历史 JSONL 记录只保存有界 profile 文本，恢复时不把它重新当作新的 delegate 请求执行；因此不需要重写历史文件。迁移范围仅包括新请求、内部 fixture、测试、文档和 schema。

### 3. 使用工具白名单落实只读，而不是依赖角色提示词

`explore` 和 `review` 的实际工具集合固定为：

```text
read, grep, find, ls, skill
```

子 Session 不装配 `write`、`edit`、`bash`、MCP 或 `delegate`。角色指令只用于引导工作方式，不能作为安全边界；权限边界必须由最终装配的工具集合和已有运行时策略落实。子 Agent 继续使用 `enable_subagents=False`，防止通过递归委派绕过最大深度。

不为 Reviewer 开放通用 `bash` 来执行 `git diff`。在本变更中，父 Agent 应通过已有有界 context 传递待审查文件、差异事实和限制；未来若需要子 Agent 自主查看差异，应新增语义明确的只读工具，而不是扩大 Shell 权限。

### 4. 复用现有上下文和结果契约

子 Agent 仍只收到 task、角色指令和显式 context，不复制父消息历史、父工具输出或隐藏状态。现有 context renderer 已将项标记为不可信数据，因此 profile 指令只需进一步要求 Reviewer 不声称检查未观察到的范围。

本变更不新增 ExploreResult 或 ReviewResult 两套结果类型。两种角色继续使用现有 `SubagentResult` 的摘要、evidence、usage 和 artifact 字段；没有机器可读 finding 时维持空列表，避免把角色文本解析成未经证实的事实。

### 5. 保持同一套运行时生命周期

profile 只决定子 Agent 的能力和提示，不创建新的状态或 runner。`SerialSubagentRunner` 仍负责请求校验、独立 Session、预算、取消、终态唯一性和资源清理；父子事件、运行记录和 TUI 委派块继续沿用现有 profile 字段。

## Risks / Trade-offs

- **[旧调用方仍发送 `read_only`]** → 在 `delegate` 边界返回明确迁移错误；更新仓库内调用、测试和文档，历史记录只读展示不参与新请求。
- **[profile schema 与实际工具再次漂移]** → 所有入口只通过 registry 获取名称、指令和白名单，并增加 schema/装配一致性契约测试。
- **[角色提示词被 context 注入覆盖]** → 延续现有 context 数据标记和字段边界；安全性以工具白名单为准，增加要求写文件、执行 Shell 和递归委派的负向测试。
- **[Reviewer 没有真正的 diff]** → 不允许它声称已检查未提供或未读取的差异；结果明确报告范围不足。自动 diff 工具留到独立变更。
- **[误把严格只读扩展到 Tester]** → 本变更不注册 Tester；测试命令执行必须在后续变更中单独设计进程、命令白名单和副作用治理。
- **[历史记录显示旧名称]** → 记录格式保持兼容并按原始有界文本展示；展示旧名称不等于重新开放旧运行入口。

## Migration Plan

1. 先增加 registry 一致性和 profile 负向测试，再将 `delegate` 默认值、schema 和运行时校验迁移到 `explore`。
2. 更新仓库内所有新的 `read_only` delegate 请求、fixture 和文档为 `explore`，保留历史记录读取测试。
3. 让应用组合层和 TUI 组合层都从同一 profile 定义装配工具和角色指令，确认子 Agent 的实际工具集合不变且不包含危险入口。
4. 完成集成测试、契约测试和 OpenSpec 校验后发布该变更。
5. 如需回滚，回退本变更代码和文档即可；本变更不改写 JSONL，不需要数据回滚。运行中的子 Agent 不在本变更中提供跨进程恢复，因此不存在需要迁移的活动子运行。
