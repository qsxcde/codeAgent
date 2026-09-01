## Context

`core/` 已定义 `SubagentRequest`、`SubagentResult`、`SubagentState` 和 `SubagentRunner`，但 core 不允许依赖 Session、模型或具体工具。现有 `AgentSession` 能独立拥有 AgentContext、EventBus、运行状态和 runtime closer；`SessionManager` 的 create/switch/fork 是用户会话切换语义，不能作为子任务调度器。现有 `AgentLoopConfig` 以 `AgentTool` 为工具端口，Session runtime 会在每次 run 建立配置副本，因此可以在执行边界绑定当前父 `run_id`。

## Goals / Non-Goals

**Goals:**

- 跑通父 Agent → `delegate` → 独立子 Agent → 结构化 `ToolResult` → 父 Agent 继续推理的真实调用链。
- 保证同一个 runner 的委派串行执行，子 Agent 使用独立 Session、上下文、运行标识和资源所有权。
- 提供安全 MVP：只读 profile、最大深度 1、子 Agent 不可继续委派；失败和取消路径都释放临时资源。
- 使 runner 可用 FakeClient 离线测试，并保持未启用 Subagent 的既有配置兼容。

**Non-Goals:**

- 不实现并行调度、`review`/写入 profile、完整预算/超时策略、长期记忆或远程 worker。
- 不把子 Agent 全量 transcript、独立子会话或新的 JSONL entry 写入持久化存储。
- 不在本变更中完成 TUI/CLI 委派块、完整父子事件渲染和结构化证据模型；只保留 runner 需要的关联字段。

## Decisions

### 1. 在组合层实现 runner 和 delegate tool

新增 `app/composition/subagent/runner.py`、`delegate_tool.py` 和必要的 `factory.py`。`DelegateTool` 只依赖 core 的 `AgentTool`、Subagent contract 和 `ToolResult`；runner 通过注入的 child-session factory 创建实际 Session。这样 core 保持 provider-neutral，工具层也不需要知道 Agent 生命周期。

备选方案是把子 Agent 逻辑放进 `core/orchestration` 或 `tools/atomic`。前者会反向依赖 Session/资源，后者无法表达独立上下文与关闭顺序，均违反现有边界。

### 2. 子运行使用注入的临时 AgentSession，而不是 SessionManager

组合根创建一个串行 runner，并注入一个只创建临时、非持久化子 Session 的闭包。闭包使用父级的模型/工作目录/基础策略配置，但以 `enable_subagents=False` 创建子配置；子 Session 自己拥有 EventBus 和 runtime closer，runner 在 `execute` 的 `finally` 中关闭它。子任务只以任务文本和明确的只读 profile 启动，不复制父历史。

备选方案是调用 SessionManager 的 `switch`、`fork` 或把子任务放入当前 Session。这些操作会改变当前用户会话、共享历史或覆盖订阅状态，不能表示临时子运行。

### 3. 每次执行绑定不可共享的父运行标识

`DelegateTool` 提供返回副本的 `bind_parent_run_id(run_id)` 方法。Session execution 在复制 `AgentLoopConfig` 和工具列表时，对支持该方法的工具绑定当前 run；配置对象和原始工具模板不保存上一次运行的父 ID。工具执行时生成新的 `delegation_id`，只接受内部绑定的父 run ID，不信任模型参数传入的关联标识。

备选方案是把 `run_id` 加到 `AgentTool.execute` 公共接口，这会破坏现有工具端口并迫使所有工具迁移；也不使用进程级全局变量，避免并发 Session 串扰。

### 4. 以有界 ToolResult 回填父上下文

子 Agent 正常完成时，runner 从子 Session 的最终输出提取有限摘要，并携带委派和子运行关联信息；失败、拒绝或取消时通过 `ToolResult.error/status/details` 表达，不把异常对象或完整子历史泄漏给父 Agent。父 ReAct 循环继续按普通工具结果处理，父会话提交时只会看到自己的用户、模型和 `delegate` tool message。

结构化发现、证据、artifact 和用量字段由后续 result-observability 变更扩展；本阶段不提前改变 core 结果契约。

### 5. 串行锁只覆盖子运行，不改变父会话调度

runner 使用单个异步锁保证同一 runner 同时只有一个子 Session 进入 `run`；后续委派在锁上等待并按到达顺序启动。活动表按 `delegation_id` 记录子任务和 task，`cancel` 只定位对应活动任务/Session。父 Agent 本身仍由现有 SessionManager/SessionRuntime 管理，二者不共享当前会话指针。

## Risks / Trade-offs

- [子任务等待会增加父工具调用延迟] → MVP 明确采用串行模型，并通过独立生命周期保证行为可解释；后续并行调度另行引入全局预算和冲突策略。
- [子 Agent 失败后父 Agent 可能过度相信自然语言] → 结果携带稳定 status、reason code 和 error 标记；证据字段在后续变更中补齐。
- [子 Session 关闭失败会泄漏资源] → runner 在成功、异常和取消路径统一执行 `cancel_and_wait`/`close`，测试检查活动任务和 fake client 的关闭状态。
- [共享基础配置可能误注入 delegate] → child-session factory 显式关闭 Subagent 装配，测试断言子 Agent 工具列表不含 `delegate`。
- [旧的直接 `create_agent_config` 调用未提供 runner] → runner 参数保持可选，默认不增加工具；现有单 Agent 测试和调用方无需迁移。

## Migration Plan

1. 先补充 delegate、runner、Session 装配和 FakeClient 的失败测试，再实现最小运行链。
2. 将根 Session/Manager 的配置接入 runner，并保持 `enable_subagents=False` 的子工厂路径。
3. 运行单元、契约、集成、Ruff、OpenSpec 和全量离线测试；更新 v0.5 迭代记录。
4. 回滚时移除 root runner 注入并保留 core 契约；未持久化子会话不会留下迁移数据。

## Open Questions

无。本阶段的并行、预算、证据、持久化和 TUI 范围已明确推迟到后续变更，不影响当前实现。
