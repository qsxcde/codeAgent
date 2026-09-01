## ADDED Requirements

### Requirement: Subagent 委派块

TUI SHALL 为每个 `delegation_id` 渲染独立的委派块，并按结构化 Subagent 事件原位更新其状态、阶段、耗时、有限任务标签/profile、child run 标识、结果摘要和诊断。委派块 SHALL 与普通工具调用块视觉和语义分离；默认 SHALL 折叠，不得因为子 Agent transcript 增长而复制或展开完整子消息。

#### Scenario: 委派块随事件更新

- **WHEN** TUI 依次收到同一委派的排队、启动、进度和终态事件
- **THEN** 聊天区保留一个委派块并更新该块内容，不追加多份相同委派的块

#### Scenario: 委派块默认紧凑

- **WHEN** 子 Agent 正在运行或已经完成
- **THEN** 默认视图显示状态、阶段、耗时和有限摘要；子 Agent 的完整正文、工具输出和显式上下文不进入默认聊天区

#### Scenario: 委派块可查看有限详情

- **WHEN** 用户点击委派块
- **THEN** TUI 在不阻塞输入的前提下展开/折叠有限的关联 ID、reason code、清理诊断、结果统计或短摘要，且展开内容仍受长度和行数上限约束

### Requirement: 委派状态栏聚合

TUI 底部状态栏 SHALL 在既有固定运行槽位内提供委派数量或状态聚合，例如运行中、等待确认和失败数量；聚合 SHALL 不显示完整任务文本，不改变会话区和上下文区的固定边界，并在窄终端按既有优先级截断或隐藏次要委派信息。

#### Scenario: 聚合随多个委派变化

- **WHEN** 父会话中有多个委派分别处于运行、等待确认或失败状态
- **THEN** 状态栏显示有限聚合，数量和状态变化只更新运行状态区，不推动模型、工作目录或上下文区域

#### Scenario: 没有活动委派

- **WHEN** 当前没有活动委派且历史委派均已进入终态
- **THEN** 状态栏不遗留运行中数量，普通会话阶段和耗时显示保持原有语义

### Requirement: 委派展示性能与离线可测

TUI 对 Subagent 事件的处理 SHALL 是事件驱动且可离线测试；进度事件 SHALL 更新有界状态并触发受控帧刷新，不得同步遍历或重新解析完整 transcript。委派投影、诊断文本、事件去重和布局缓存 SHALL 有明确上限，多个委派和长会话下的滚动、resize、点击、输入及取消 SHALL 继续满足既有流式渲染控制延迟目标。

#### Scenario: 高频进度不导致完整历史重渲染

- **WHEN** 单个子 Agent 连续产生大量有界进度事件，而父会话包含长历史
- **THEN** TUI 只更新对应委派块及必要的可见布局，事件和缓存占用保持在固定上限内，输入和取消不会被长期阻塞

#### Scenario: 专用事件不改变父运行阶段

- **WHEN** TUI 收到 child session/run 的 `SUBAGENT_PROGRESS` 或 `SUBAGENT_FINISHED`
- **THEN** 父级 runtime phase、当前父 run/session 标识和普通 assistant 正文保持不变，只有对应委派投影和聚合状态更新

#### Scenario: 离线渲染断言

- **WHEN** 测试注入确定性的 Subagent 事件序列并渲染指定宽高
- **THEN** 可以断言状态文本、样式标签、终态幂等、关联隔离和有界输出，而无需真实终端、模型或网络
