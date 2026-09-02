## Why

当前 Subagent runtime 只有 `read_only` 和 `review` 两个字符串 profile，二者使用相同的工具白名单，无法清晰表达“探索”和“审查”的职责边界；同时 `delegate` schema、子会话装配和角色提示词分别依赖硬编码，后续扩展角色容易出现入口与实际权限不一致。现在先固定严格只读角色契约，可以在引入测试执行、并行调度或可写隔离前建立稳定的能力边界。

## What Changes

- 增加应用组合层的 Subagent profile registry，集中管理 profile 名称、职责说明、工具白名单和输出要求。
- 将 `explore` 定义为正式的只读代码探索 profile，允许读取、搜索、目录查询和技能查询，不允许写文件、编辑、Shell、MCP 或再次委派。
- 保留并明确 `review` 的只读审查语义；审查范围必须来自父 Agent 显式提供的有界 context，不隐式继承父会话历史或工作区状态。
- 更新 `delegate` 的 schema、参数校验、子 Session 工厂和运行器，使它们从同一个 registry 解析 profile，避免 schema 与实际装配能力不一致。
- **BREAKING** 将运行入口中的 `read_only` 更名为 `explore`，不再接受 `read_only` 作为新的 delegate 请求 profile；历史父会话中的旧 profile 字符串仍作为有界记录读取和展示，不回写历史文件。
- 保持现有 Subagent 生命周期、预算、事件、结果结构、父会话运行记录和 TUI 投影语义不变。
- 明确 `tester` 不属于本变更；测试命令执行、进程副作用和专用验证工具另行建立变更。

## Capabilities

### New Capabilities

<!-- No new capability spec is needed; the behavior extends the existing Subagent runtime contract. -->

### Modified Capabilities

- `subagent-runtime`: 修改可用 profile、只读工具能力、显式审查上下文和 profile 解析一致性要求。

## Impact

- 影响 `src/codeagent/app/composition/subagent/` 下的 profile registry、`delegate` 适配器、子会话工厂和运行器校验。
- 影响 `delegate` 工具的公开参数 schema 和默认 profile；调用方需要将 `read_only` 请求迁移为 `explore`。
- 影响 Subagent 相关应用层、契约层和集成测试，以及 v0.5 迭代文档和 Subagent runtime delta spec。
- 不新增第三方依赖，不修改 `core` 的 provider-neutral 生命周期；仅同步 `SubagentRequest` 的默认 profile 字符串为 `explore`，不把 profile registry 或权限策略放入 core；不改变 `session` 的持久化格式，也不开放 Shell、MCP 或写入工具。
