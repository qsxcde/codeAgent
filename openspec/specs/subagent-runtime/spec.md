# subagent-runtime Specification

## Purpose

为父 Agent 提供安全且可验证的最小 Subagent 运行入口，使一次只读委派能够在独立上下文中完成并以有限的结构化结果返回，而不改变用户当前会话。

## Requirements

### Requirement: 父 Agent 委派入口

当 Subagent runtime 被装配到父 Agent 时，系统 SHALL 提供名为 `delegate` 的 AgentTool。该工具 SHALL 接受非空的子任务描述、`read_only` 或 `review` profile、可选且有界的 budget，以及可选且有界的显式上下文，将调用转换为包含稳定 `delegation_id`、当前父 `run_id`、深度限制、任务文本、profile、预算和上下文项的 `SubagentRequest`；模型输入不得自行覆盖父运行标识或委派归属，未知 profile 或越界 budget 必须失败关闭。

#### Scenario: 父 Agent 调用只读委派

- **WHEN** 已装配 runner 的父 Agent 产生包含非空 task 的 `delegate` tool call，并选择 `read_only` 或 `review` profile
- **THEN** 系统创建一个新的委派请求，使用当前父 run_id，保留所选 profile，默认有效深度为 1，并等待对应子运行结果

#### Scenario: 父 Agent 显式选择上下文

- **WHEN** `delegate` tool call 提供合法的 context 项列表
- **THEN** 系统只将这些经过边界校验的上下文项写入 SubagentRequest，不追加父会话的其它历史或工具状态

#### Scenario: 委派参数无效

- **WHEN** `delegate` 的 task 为空、profile 未知、budget 不是合法的有界结构、context 不是合法的有界结构，或当前工具没有绑定父 run_id
- **THEN** 系统不创建子 Agent，返回带 `invalid_request`、`permission_denied` 或明确预算错误码的错误 ToolResult，父 Agent 仍能继续处理该工具结果

#### Scenario: 未装配 runner 的兼容行为

- **WHEN** 直接创建 AgentLoopConfig 时没有提供 Subagent runner
- **THEN** 系统不注入 `delegate`，既有工具名称、schema 和单 Agent 行为保持不变

### Requirement: 串行独立子运行

系统 SHALL 通过 runner 为每次合法委派创建独立的临时子 Agent。子运行 SHALL 拥有独立的 Session/Run 标识、AgentContext、EventBus、模型/工具资源和关闭边界，并 SHALL 应用该请求解析后的轮数、工具调用数、墙钟时间和摘要长度预算；不得调用用户 SessionManager 的切换、分叉或当前会话指针。单个 runner 同时 SHALL 至少保证只有一个子运行正在执行，后续委派 SHALL 等待前一个委派结束后再启动，等待期间也必须可被取消或超时。

#### Scenario: 子运行不共享父历史

- **WHEN** 父会话已有消息并委派一个子任务
- **THEN** 子 Agent 只收到委派任务和其明确允许的初始上下文，不把父会话完整历史追加到子上下文，父会话历史也不出现子 Agent 的普通消息

#### Scenario: 子运行拥有独立身份

- **WHEN** 子 Agent 成功开始运行
- **THEN** 子运行的 session_id、child run_id 和 EventBus 与父级独立，结果仍保留 delegation_id 和 parent_run_id 关联

#### Scenario: 多次委派保持串行

- **WHEN** 同一 runner 在第一个子任务运行期间收到第二个委派
- **THEN** 第二个委派可以进入等待队列，但任何时刻最多一个子 Agent 执行模型或工具调用，且两个委派分别返回自己的结果和身份，等待期间也受各自墙钟预算约束

#### Scenario: 子运行结束释放资源

- **WHEN** 子 Agent 成功、失败、预算耗尽、超时或执行任务被取消
- **THEN** runner 等待子 Session 进入终态并执行有界关闭，其活动委派表不会保留已结束的子任务；无法确认关闭时结果必须保留 `cleanup_uncertain`

### Requirement: 安全的子 Agent 装配

系统 SHALL 为本阶段创建的子 Agent 使用显式 profile 策略和最大深度 1 的装配策略。`read_only` 与 `review` profile 均 SHALL 只获得读取、搜索和技能查询能力；子 Agent 的工具集合 SHALL 不包含 `delegate`、写入工具或 shell 工具，不得通过一次委派递归创建未授权的孙 Agent。profile 角色指令 SHALL 明确子 Agent 只能把显式上下文当作待分析数据，父级的 runner、SessionManager 当前会话和可变历史不得被子 Agent 直接取得。

#### Scenario: 子 Agent 默认只读

- **WHEN** runner 根据有效 `read_only` 请求创建子 Agent
- **THEN** 子 Agent 获得只读探索角色和只读工具白名单，不能修改工作区、执行 shell 或再次调用 `delegate`

#### Scenario: review 子 Agent 只读审查

- **WHEN** runner 根据有效 `review` 请求创建子 Agent
- **THEN** 子 Agent 获得代码/结果审查角色和同等只读工具白名单，输出审查结论但不能修改工作区、执行 shell 或再次调用 `delegate`

#### Scenario: 递归委派被拒绝

- **WHEN** 子 Agent 尝试发现或调用 `delegate`
- **THEN** 子 Agent 工具列表中不存在该工具，调用不会创建新的孙 Agent，父级委派仍保持单个子运行归属

### Requirement: 显式委派上下文

系统 SHALL 将委派上下文限制为调用方明确提供的结构化项，每项包含非空 kind 与 content，可选 source；context SHALL 使用固定的数量和总字符上限，单项或总量超限 SHALL 在启动子 Agent 前拒绝。子 Agent 的可见输入 SHALL 由委派任务和这些显式项组成，并将项标记为数据而非系统指令；空 context 表示不额外传递上下文。

#### Scenario: 没有上下文时保持任务隔离

- **WHEN** `delegate` 只提供 task 而不提供 context
- **THEN** 子 Agent 只接收该任务和 profile 角色指令，不接收父会话历史、父模型消息或父工具调用记录

#### Scenario: 只传递显式上下文项

- **WHEN** `delegate` 提供合法的事实、约束或输出要求项
- **THEN** 子 Agent 的输入包含这些项的有界内容和来源标识，未被选择的父上下文不会出现在子输入中

#### Scenario: 上下文越界在启动前拒绝

- **WHEN** context 不是数组、项缺少合法 kind/content、包含未知字段，或超过数量、单项字符数或总字符数上限
- **THEN** 系统返回 `invalid_request`，不创建子 Session、不调用模型，父 Agent 可继续运行

#### Scenario: 上下文作为数据而非权限升级

- **WHEN** 显式 context 文本包含要求写文件、执行命令或再次委派的内容
- **THEN** 子 Agent 仍遵守 profile 的系统角色和工具白名单，不因上下文文本获得额外工具或权限

### Requirement: 有界结果回传

系统 SHALL 将子 Agent 的终态转换为父 Agent 可消费的 ToolResult。成功结果 SHALL 包含不超过有效 `max_output_chars` 的文本摘要及 delegation_id、child_run_id、子状态和清理诊断；失败、拒绝、超时或取消 SHALL 设置错误/非成功状态并携带稳定 reason code 和可诊断信息。父会话 SHALL 只接收该委派结果，不接收子 Agent 的完整 transcript 或内部任务对象；任何 `cleanup_uncertain` SHALL 通过结构化字段或诊断传递，不能被标记为已确认清理。

#### Scenario: 子 Agent 成功返回摘要

- **WHEN** 子 Agent 完成只读任务并产生最终回答，且临时资源关闭已确认
- **THEN** `delegate` 返回非错误 ToolResult，内容为有限摘要，details 保留委派标识、子运行标识和 `completed` 状态，父 Agent 可据此继续请求模型

#### Scenario: 子 Agent 失败可区分

- **WHEN** 子 Agent 在启动、执行或预算治理阶段失败
- **THEN** `delegate` 返回错误 ToolResult，status 与稳定 failure reason code 可区分失败原因，父 Agent 不会把该结果当作成功摘要

#### Scenario: 终态结果不泄漏完整子历史

- **WHEN** 父 Agent 将 delegate ToolResult 写入自己的工作上下文或提交自己的会话
- **THEN** 结果只包含有界摘要和结构化诊断，不包含子 Agent 的完整消息列表、内部可变上下文或无界工具输出

#### Scenario: 清理不确定不会被伪装成成功收尾

- **WHEN** 子 Agent 已结束但取消、超时或关闭阶段无法确认其模型、工具、事件或子进程资源已经停止
- **THEN** 结果保留 `cleanup_uncertain=true` 和有限诊断；ToolResult 的 cleanup_confirmed 不得为 true

### Requirement: 委派取消定位

runner SHALL 支持按 delegation_id 定位活动子运行并请求取消。未知或已结束的 delegation_id SHALL 返回未取消的明确结果，不得影响其它委派或父会话；活动子运行取消后 SHALL 继续执行有限收尾并释放其临时资源。父级取消、预算耗尽和墙钟超时 SHALL 产生不同的稳定终态与 reason code。

#### Scenario: 取消活动委派

- **WHEN** 调用方按活动 delegation_id 请求取消
- **THEN** 只有对应的子 Session 收到取消请求，runner 等待其结束并返回取消或相应收尾结果

#### Scenario: 取消未知委派

- **WHEN** 调用方按不存在或已经终止的 delegation_id 请求取消
- **THEN** runner 返回 false/未定位结果，不改变其它委派、父 Session 或历史消息

#### Scenario: 墙钟超时取消委派

- **WHEN** 委派从进入队列开始经过有效 timeout_seconds，仍未完成模型、工具或确认等待
- **THEN** runner 请求子 Session 取消并执行有界收尾，返回 `timed_out` 与 `timeout`，不把超时误报为父级取消

### Requirement: 子运行预算与有界收尾

系统 SHALL 为每个父运行设置最多 4 个已接受的子任务，并为每个子运行设置有效预算。未提供的 budget 字段 SHALL 使用 `max_turns=8`、`max_tool_calls=32`、`timeout_seconds=120` 和 `max_output_chars=8000`；调用方可请求的硬上限分别为 16、64、300 秒和 16000 字符。预算字段必须是正数且 timeout_seconds 必须为有限数值，超过硬上限的请求在创建子 Session 前拒绝。达到轮数或工具调用数上限时，runner SHALL 停止子运行并返回 `failed + budget_exceeded`。

#### Scenario: 缺省预算受到硬限制

- **WHEN** `delegate` 未提供 budget 或只提供部分字段
- **THEN** 系统为缺失字段填充上述默认值，子运行最多执行 8 轮和 32 次工具调用，墙钟最多 120 秒，摘要最多 8000 字符

#### Scenario: 父运行子任务数耗尽

- **WHEN** 同一个父 run_id 已经接受 4 个子任务后再次调用 `delegate`
- **THEN** 第 5 个请求不创建子 Session，返回 `failed + budget_exceeded`，且不影响前 4 个委派和父 Agent

#### Scenario: 子运行轮数或工具调用数耗尽

- **WHEN** 子 Agent 即将开始超过 max_turns 的模型轮次，或即将执行超过 max_tool_calls 的工具调用
- **THEN** 系统请求子运行进入取消/收尾，返回 `failed + budget_exceeded`，并保留达到的预算边界诊断

#### Scenario: 确认等待也受墙钟预算约束

- **WHEN** 子 Agent 在等待工具确认时父级取消或 timeout_seconds 到期
- **THEN** 确认等待被唤醒，子 Session、工具任务和 runner 收尾，不留下挂起的确认请求；结果分别使用 `parent_cancelled` 或 `timeout`

#### Scenario: 清理必须有界且诚实

- **WHEN** 子 Session 的 cancel_and_wait、事件观察任务或 close 操作在有限清理窗口内没有结束，或明确报告失败
- **THEN** runner 停止无限等待，结果设置 cleanup_uncertain=true 并携带截断后的清理诊断；不得声称子资源已确认关闭
