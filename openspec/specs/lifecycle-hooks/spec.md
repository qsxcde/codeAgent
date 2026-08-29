# lifecycle-hooks Specification

## Purpose

为运行时扩展提供统一、只读且可关联的生命周期观察能力，让审计、遥测和后续记忆实现无需侵入 Agent 主循环即可消费稳定事件。

## Requirements

### Requirement: 统一生命周期 Hook 契约

系统 SHALL 提供 provider-neutral 的生命周期 Hook 事件，事件至少包含 `scope`、`phase`、原始结构化事件、`run_id` 和可选的 `session_id`；`scope` SHALL 支持 `turn`、`model`、`tool` 和 `session`，`phase` SHALL 支持 `started`、`updated` 和 `finished`。

#### Scenario: Hook 收到结构化生命周期事件

- **WHEN** Agent 运行产生 turn、model 或 tool 生命周期事件
- **THEN** 注册的 Hook 按事件产生顺序收到对应 scope 和 phase 的事件，并能通过 `run_id` 关联同一次运行

#### Scenario: Session Hook 收到会话关联

- **WHEN** session 发布会话开始、更新或结束事件
- **THEN** Hook 收到 `scope=session` 的事件，事件携带当前 `session_id` 和运行关联信息

### Requirement: 观察 Hook 不改变主流程

系统 SHALL 允许注册多个只读观察 Hook，并按注册顺序调用；Hook 的返回值 SHALL 被忽略，不得改变上下文、工具决策、事件终态、持久化或取消语义。

#### Scenario: 多个 Hook 保持注册顺序

- **WHEN** 同一生命周期事件被多个 Hook 观察
- **THEN** Hook 按注册顺序各收到一次同一事件快照

#### Scenario: Hook 返回值不参与控制

- **WHEN** Hook 返回任意值或尝试通过返回值表示拒绝、替换或重试
- **THEN** Agent 继续按照原有运行、工具和持久化规则执行，Hook 返回值不产生控制效果

### Requirement: 生命周期覆盖开始更新结束

系统 SHALL 为 turn、model、tool 和 session 提供开始、更新和结束观察；模型流式输出、预算/用量和工具排队/进度 SHALL 作为更新事件，取消和失败 SHALL 通过结构化结束事件保留结果状态。

#### Scenario: 模型请求边界可观察

- **WHEN** 一次模型请求开始、产生流式内容并正常结束
- **THEN** Hook 依次收到 model started、一个或多个 updated 和 finished 事件

#### Scenario: 工具排队和执行可观察

- **WHEN** 工具调用进入队列、开始执行、产生进度并结束
- **THEN** Hook 收到同一工具关联信息下的 tool started、updated 和 finished 事件，且结束事件保留工具状态

#### Scenario: 取消仍有结束观察

- **WHEN** Agent 或 session 在 turn、模型请求或工具执行期间被取消
- **THEN** 对应 Hook 收到 finished 事件或带取消状态的 session finished 事件，且主流程完成既有清理和回滚

### Requirement: Hook 接入保持分层

生命周期 Hook 契约 SHALL 仅依赖 core/session 可共享的结构化类型；具体 Hook 实现不得被 core 直接导入，应用组合根负责把 Hook 注入运行配置。

#### Scenario: 核心运行不依赖具体扩展

- **WHEN** 不提供任何 Hook 或提供仅实现协议的测试 Hook
- **THEN** Agent Runtime 可以独立运行，core 不加载 provider、tools、MCP、Skill 或 UI 实现
