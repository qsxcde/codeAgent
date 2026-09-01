# subagent-runtime Specification

## Purpose

为父 Agent 提供安全且可验证的最小 Subagent 运行入口，使一次只读委派能够在独立上下文中完成并以有限的结构化结果返回，而不改变用户当前会话。

## Requirements

### Requirement: 父 Agent 委派入口

当 Subagent runtime 被装配到父 Agent 时，系统 SHALL 提供名为 `delegate` 的 AgentTool。该工具 SHALL 接受非空的子任务描述和可选的只读 profile，将调用转换为包含稳定 `delegation_id`、当前父 `run_id`、深度限制和任务文本的 `SubagentRequest`；模型输入不得自行覆盖父运行标识或委派归属。

#### Scenario: 父 Agent 调用只读委派

- **WHEN** 已装配 runner 的父 Agent 产生包含非空 task 的 `delegate` tool call
- **THEN** 系统创建一个新的委派请求，使用当前父 run_id，默认 profile 为 `read_only`、有效深度为 1，并等待对应子运行结果

#### Scenario: 委派参数无效

- **WHEN** `delegate` 的 task 为空、profile 不是当前允许的 `read_only`，或当前工具没有绑定父 run_id
- **THEN** 系统不创建子 Agent，返回带 `invalid_request` 或 `permission_denied` 的错误 ToolResult，父 Agent 仍能继续处理该工具结果

#### Scenario: 未装配 runner 的兼容行为

- **WHEN** 直接创建 AgentLoopConfig 时没有提供 Subagent runner
- **THEN** 系统不注入 `delegate`，既有工具名称、schema 和单 Agent 行为保持不变

### Requirement: 串行独立子运行

系统 SHALL 通过 runner 为每次合法委派创建独立的临时子 Agent。子运行 SHALL 拥有独立的 Session/Run 标识、AgentContext、EventBus、模型/工具资源和关闭边界；不得调用用户 SessionManager 的切换、分叉或当前会话指针。单个 runner 同时 SHALL 至少保证只有一个子运行正在执行，后续委派 SHALL 等待前一个委派结束后再启动。

#### Scenario: 子运行不共享父历史

- **WHEN** 父会话已有消息并委派一个子任务
- **THEN** 子 Agent 只收到委派任务和其明确允许的初始上下文，不把父会话完整历史追加到子上下文，父会话历史也不出现子 Agent 的普通消息

#### Scenario: 子运行拥有独立身份

- **WHEN** 子 Agent 成功开始运行
- **THEN** 子运行的 session_id、child run_id 和 EventBus 与父级独立，结果仍保留 delegation_id 和 parent_run_id 关联

#### Scenario: 多次委派保持串行

- **WHEN** 同一 runner 在第一个子任务运行期间收到第二个委派
- **THEN** 第二个委派可以进入等待队列，但任何时刻最多一个子 Agent 执行模型或工具调用，且两个委派分别返回自己的结果和身份

#### Scenario: 子运行结束释放资源

- **WHEN** 子 Agent 成功、失败或执行任务被取消
- **THEN** runner 等待子 Session 收尾并关闭其模型、工具和事件资源，活动委派表不会保留已结束的子任务

### Requirement: 安全的子 Agent 装配

系统 SHALL 为本阶段创建的子 Agent 使用只读 profile 和最大深度 1 的装配策略。子 Agent 的工具集合 SHALL 不包含 `delegate`，不得通过一次委派递归创建未授权的孙 Agent；父级的 runner、SessionManager 当前会话和可变历史不得被子 Agent 直接取得。

#### Scenario: 子 Agent 默认只读

- **WHEN** runner 根据有效 `read_only` 请求创建子 Agent
- **THEN** 子 Agent 获得只读能力边界，不能通过本次装配直接执行写入型委派或再次调用 `delegate`

#### Scenario: 递归委派被拒绝

- **WHEN** 子 Agent 尝试发现或调用 `delegate`
- **THEN** 子 Agent 工具列表中不存在该工具，调用不会创建新的孙 Agent，父级委派仍保持单个子运行归属

### Requirement: 有界结果回传

系统 SHALL 将子 Agent 的终态转换为父 Agent 可消费的 ToolResult。成功结果 SHALL 包含有限的文本摘要及 delegation_id、child_run_id 和子状态；失败、拒绝或取消 SHALL 设置错误/非成功状态并携带稳定 reason code 和可诊断信息。父会话 SHALL 只接收该委派结果，不接收子 Agent 的完整 transcript 或内部任务对象。

#### Scenario: 子 Agent 成功返回摘要

- **WHEN** 子 Agent 完成只读任务并产生最终回答
- **THEN** `delegate` 返回非错误 ToolResult，内容为有限摘要，details 保留委派标识、子运行标识和 `completed` 状态，父 Agent 可据此继续请求模型

#### Scenario: 子 Agent 失败可区分

- **WHEN** 子 Agent 在启动或执行阶段失败
- **THEN** `delegate` 返回错误 ToolResult，status 与稳定 failure reason code 可区分失败原因，父 Agent 不会把该结果当作成功摘要

#### Scenario: 终态结果不泄漏完整子历史

- **WHEN** 父 Agent 将 delegate ToolResult 写入自己的工作上下文或提交自己的会话
- **THEN** 结果只包含有界摘要和结构化诊断，不包含子 Agent 的完整消息列表、内部可变上下文或无界工具输出

### Requirement: 委派取消定位

runner SHALL 支持按 delegation_id 定位活动子运行并请求取消。未知或已结束的 delegation_id SHALL 返回未取消的明确结果，不得影响其它委派或父会话；活动子运行取消后 SHALL 继续执行有限收尾并释放其临时资源。

#### Scenario: 取消活动委派

- **WHEN** 调用方按活动 delegation_id 请求取消
- **THEN** 只有对应的子 Session 收到取消请求，runner 等待其结束并返回取消或相应收尾结果

#### Scenario: 取消未知委派

- **WHEN** 调用方按不存在或已经终止的 delegation_id 请求取消
- **THEN** runner 返回 false/未定位结果，不改变其它委派、父 Session 或历史消息
