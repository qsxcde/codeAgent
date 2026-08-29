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

### Requirement: Hook 异常诊断与隔离

生命周期 Hook、Hook 返回的异步结果以及为 Hook 构造脱离原始事件的快照时发生的普通异常 SHALL 被隔离，并以结构化运行期诊断记录暴露。诊断至少 SHALL 包含稳定的错误代码、Hook 身份或快照阶段标识、scope/phase（可确定时）、事件类型、run/session 关联、失败阶段、异常类型和消息。Hook 失败 SHALL 不改变其它 Hook 的调用、Agent 主循环、会话提交/回滚、取消收尾或资源清理语义；Hook 诊断 SHALL 不写入用户会话历史或持久化记录。取消异常 SHALL 继续遵循既有取消传播，不得被误报为 Hook 失败。

#### Scenario: 同步 Hook 失败仍继续运行

- **WHEN** 一个同步 Hook 在生命周期事件上抛出普通异常
- **THEN** 该异常被记录为可查询的结构化诊断，后续 Hook 仍按注册顺序收到事件，Agent 运行和最终状态不受影响

#### Scenario: 异步 Hook 失败仍完成收尾

- **WHEN** 一个异步 Hook 在等待期间抛出普通异常
- **THEN** 异常在运行期 Hook 任务收尾时被记录，Agent 或 Session 仍完成既有成功/失败/取消收尾，且不存在未回收的 Hook 任务

#### Scenario: 快照构造失败不穿透主流程

- **WHEN** 生命周期事件包含无法复制的负载或元数据，导致 Hook 快照构造失败
- **THEN** 系统记录快照阶段诊断、跳过该事件的 Hook 分发，并继续发布原有运行事件和执行主流程

#### Scenario: Session 诊断覆盖两侧 Hook

- **WHEN** core Hook 或 session Hook 失败
- **THEN** AgentSession 可查询带 scope、phase、事件类型和 session/run 关联的对应诊断；诊断不会出现在会话历史或 JSONL 记录中

#### Scenario: 取消不伪造 Hook 失败

- **WHEN** 运行取消时正在等待的异步 Hook 被取消
- **THEN** 取消按既有语义传播并完成任务清理，不把 `CancelledError` 记录为普通 Hook 异常
