## MODIFIED Requirements

### Requirement: 父 Agent 委派入口

当 Subagent runtime 被装配到父 Agent 时，系统 SHALL 提供名为 `delegate` 的 AgentTool。该工具 SHALL 接受非空的子任务描述、`explore` 或 `review` profile、可选且有界的 budget，以及可选且有界的显式上下文，将调用转换为包含稳定 `delegation_id`、当前父 `run_id`、深度限制、任务文本、profile、预算和上下文项的 `SubagentRequest`；模型输入不得自行覆盖父运行标识或委派归属，未知 profile 或越界 budget 必须失败关闭。省略 profile 时 SHALL 使用 `explore`。

#### Scenario: 父 Agent 调用只读委派

- **WHEN** 已装配 runner 的父 Agent 产生包含非空 task 的 `delegate` tool call，并选择 `explore` 或 `review` profile
- **THEN** 系统创建一个新的委派请求，使用当前父 run_id，保留所选 profile，默认有效深度为 1，并等待对应子运行结果

#### Scenario: 父 Agent 省略 profile

- **WHEN** `delegate` tool call 只提供非空 task 而没有提供 profile
- **THEN** 系统将 profile 解析为 `explore`，并使用 explore 的角色指令和只读工具策略创建子运行

#### Scenario: 父 Agent 显式选择上下文

- **WHEN** `delegate` tool call 提供合法的 context 项列表
- **THEN** 系统只将这些经过边界校验的上下文项写入 SubagentRequest，不追加父会话的其它历史或工具状态

#### Scenario: 委派参数无效

- **WHEN** `delegate` 的 task 为空、profile 未知或为已移除的 `read_only`、budget 不是合法的有界结构、context 不是合法的有界结构，或当前工具没有绑定父 run_id
- **THEN** 系统不创建子 Agent，返回带 `invalid_request`、`permission_denied` 或明确预算错误码的错误 ToolResult，父 Agent 仍能继续处理该工具结果

#### Scenario: 未装配 runner 的兼容行为

- **WHEN** 直接创建 AgentLoopConfig 时没有提供 Subagent runner
- **THEN** 系统不注入 `delegate`，既有工具名称、schema 和单 Agent 行为保持不变

### Requirement: 安全的子 Agent 装配

系统 SHALL 为本阶段创建的子 Agent 使用显式 profile 策略和最大深度 1 的装配策略。`explore` 与 `review` profile 均 SHALL 只获得读取、搜索、目录查询和技能查询能力；子 Agent 的工具集合 SHALL 不包含 `delegate`、写入工具、编辑工具、shell 工具或 MCP 工具，不得通过一次委派递归创建未授权的孙 Agent。profile 角色指令 SHALL 明确子 Agent 只能把显式上下文当作待分析数据，父级的 runner、SessionManager 当前会话和可变历史不得被子 Agent 直接取得。

#### Scenario: 子 Agent 默认只读

- **WHEN** runner 根据有效 `explore` 请求创建子 Agent
- **THEN** 子 Agent 获得代码探索角色和只读工具白名单，不能修改工作区、执行 shell 或再次调用 `delegate`

#### Scenario: review 子 Agent 只读审查

- **WHEN** runner 根据有效 `review` 请求创建子 Agent
- **THEN** 子 Agent 获得代码/结果审查角色和同等只读工具白名单，输出审查结论但不能修改工作区、执行 shell 或再次调用 `delegate`

#### Scenario: profile 角色策略不改变工具边界

- **WHEN** 显式 context 文本或 task 文本要求子 Agent 写文件、执行命令、调用 MCP 或再次委派
- **THEN** 子 Agent 仍遵守对应 profile 的工具白名单，文本内容不能升级工具权限或改变最大深度

#### Scenario: 递归委派被拒绝

- **WHEN** explore 或 review 子 Agent 尝试发现或调用 `delegate`
- **THEN** 子 Agent 工具列表中不存在该工具，调用不会创建新的孙 Agent，父级委派仍保持单个子运行归属

## ADDED Requirements

### Requirement: Profile registry 与入口策略一致

系统 SHALL 为每个可用 Subagent profile 维护一份稳定的能力定义，并使用同一份定义生成 `delegate` 的可选 profile、请求校验、子会话工具白名单和角色指令。对外展示为可用 profile 的名称 SHALL 都能被运行器接受；运行器接受的 profile SHALL 具有明确的角色指令和工具策略，不得出现 schema 宣传的能力与实际装配能力不一致的情况。

#### Scenario: profile 枚举与运行时一致

- **WHEN** 调用方读取 `delegate` 的参数 schema 并选择其中一个 profile
- **THEN** 该 profile 能通过请求校验，并以同一 profile 的角色指令和工具白名单创建子 Agent

#### Scenario: 未注册 profile 失败关闭

- **WHEN** `delegate` 或直接 runner 请求使用未注册的 profile
- **THEN** 系统在创建子 Session 或调用模型前拒绝请求，返回 `permission_denied`，且不产生子 Agent 副作用

#### Scenario: 已移除 profile 不作为新入口

- **WHEN** 新的 `delegate` 请求使用 `read_only` profile
- **THEN** 系统拒绝该请求并提示使用 `explore`；历史运行记录中的旧 profile 文本仍可作为有界数据读取和展示，不被自动重写

### Requirement: Reviewer 使用显式审查范围

`review` 子 Agent SHALL 只基于委派 task 和父 Agent 显式提供的 context、可直接读取的指定文件或其自身工具观察形成审查结论。它不得声称检查了未提供、未读取或未观察到的父会话历史、隐藏消息或工作区差异；当审查范围或证据不足时，结果 SHALL 明确说明范围不足，而不是猜测成功审查。

#### Scenario: Reviewer 接收显式范围

- **WHEN** 父 Agent 通过 task 或有界 context 提供待审查文件、差异事实、约束和输出要求
- **THEN** review 子 Agent 只在这些范围内读取和分析，并在摘要或证据中区分实际观察与父级提供的数据

#### Scenario: Reviewer 没有可验证范围

- **WHEN** review 子 Agent 没有获得明确的文件、差异或事实范围，也没有通过只读工具观察到对应内容
- **THEN** 子 Agent 返回范围不足或无法验证的有限结论，不把当前父会话或隐含工作区状态当作已审查证据

#### Scenario: Reviewer 不继承父历史

- **WHEN** 父会话包含未放入 context 的消息、工具输出或隐藏指令
- **THEN** review 子 Agent 的输入和结果不包含这些内容，也不会因其存在而改变 review profile 的工具权限
