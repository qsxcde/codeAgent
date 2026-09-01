## Why

V5-02 已经可以启动只读子 Agent，但 `delegate` 只能表达任务文本，子运行的角色依赖隐含的工具白名单，无法清晰区分普通探索和代码审查。现在需要把可传递上下文与角色能力显式化，避免父会话历史被隐式继承，也让权限边界可以被验证和解释。

## What Changes

- 将 `delegate` 的 profile 扩展为 `read_only` 与 `review`，未知 profile 失败关闭。
- 增加有界的显式上下文输入，将任务、事实、约束和输出要求转换为不可变的 `SubagentContextItem`。
- 为每个 profile 建立应用层能力策略和角色指令；本阶段两个 profile 都只允许读取、搜索和技能查询工具，均不包含 `delegate`、写入或 shell 工具。
- 子 Session 只接收委派任务和调用方明确提供的上下文，并把上下文标记为数据，不自动复制父历史、父工具对象或父会话状态。
- 保持省略 profile/context 的既有调用兼容，补充参数校验、越界拒绝和隔离回归测试。

## Capabilities

### New Capabilities

<!-- 本变更只细化既有 subagent-runtime 行为，不创建新的独立能力规格。 -->

### Modified Capabilities

- `subagent-runtime`: 扩展可用 profile，增加显式上下文选择和按 profile 的安全子 Agent 装配约束。

## Impact

- 影响 `app/composition/subagent/` 的 delegate 参数解析、profile 策略和子 Session 工厂，以及 runtime 配置的角色指令注入。
- 影响 `SubagentRequest.context` 的实际生产使用，但不改变 core 契约的依赖方向。
- 更新 V5.0 迭代文档和应用层回归测试；不新增第三方依赖，不改变父 SessionStore 格式。
