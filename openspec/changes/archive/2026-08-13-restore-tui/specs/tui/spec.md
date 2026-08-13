## Purpose

定义交互式终端形态(TUI)能力:MVP 子集——对话输入与流式回复渲染、运行中打断、状态栏实时反馈、alt 屏渲染、退出完整文档。TUI 通过订阅会话事件驱动,不持有对话状态,组件渲染可离线测试。

## ADDED Requirements

### Requirement: 对话输入与回复渲染

TUI SHALL 提供文本输入框;用户提交文本 SHALL 发起一轮对话,agent 的回复 SHALL 渲染到聊天区;同一会话多轮对话 SHALL 累积上下文。

#### Scenario: 发送消息

- **WHEN** 用户在输入框提交一条文本
- **THEN** 该文本作为用户消息渲染到聊天区,agent 开始回复

#### Scenario: 多轮上下文

- **WHEN** 同一会话内连续发送多条消息
- **THEN** 后续回复携带前几轮的上下文(会话维度累积)

### Requirement: 流式回复渲染

agent 回复 SHALL 以增量方式流式渲染;模型思考过程 SHALL 与正文区分展示;工具调用与结果 SHALL 在聊天区可见。

#### Scenario: 文本增量累积

- **WHEN** agent 回复流式产出文本增量
- **THEN** 正文随增量持续更新,无需等待整条回复完成

#### Scenario: 思考过程独立展示

- **WHEN** 模型产出思考增量
- **THEN** 思考内容以与正文可区分的样式展示(如折叠块)

#### Scenario: 工具调用过程可见

- **WHEN** 模型调用工具
- **THEN** 聊天区出现工具调用块,工具名称与参数可见,结果返回后更新其状态

### Requirement: 运行中打断

agent 运行中,用户 SHALL 可中断当前运行;中断后状态 SHALL 回到可输入,会话可继续。

#### Scenario: 打断运行

- **WHEN** agent 运行中用户触发中断(如 Esc)
- **THEN** 当前运行被取消,聊天区标记取消,输入框恢复可用

#### Scenario: 空闲退出

- **WHEN** agent 空闲时用户触发退出(如 Esc)
- **THEN** TUI 退出并打印完整对话文档

### Requirement: 状态栏实时反馈

TUI SHALL 提供状态栏,实时反映运行态(运行中 / 空闲 / 错误)、当前模型与 token 用量。

#### Scenario: 运行态切换

- **WHEN** agent 从空闲转为运行、或运行出错/被取消
- **THEN** 状态栏状态随之更新(运行中 / 空闲 / 错误)

#### Scenario: 用量展示

- **WHEN** 产生 token 用量事件
- **THEN** 状态栏展示最新的用量信息

### Requirement: alt 屏渲染与滚动

TUI SHALL 在 alt 屏渲染,应用自己管理滚动;流式输出 SHALL 自动跟随底部,用户上滚浏览历史后 SHALL 解除跟随,滚回底部 SHALL 恢复跟随。

#### Scenario: 流式跟底

- **WHEN** 流式输出使聊天区增长
- **THEN** 视口自动跟随底部,最新内容可见

#### Scenario: 上滚浏览历史

- **WHEN** 用户上滚查看历史
- **THEN** 视口停止跟随底部,新输出不强制跳回底部

#### Scenario: 回到底部恢复跟随

- **WHEN** 用户滚回底部
- **THEN** 视口恢复自动跟随

### Requirement: 退出完整文档

退出 alt 屏时,TUI SHALL 以完整形式输出整个对话(而非仅最后一屏),供复制留存。

#### Scenario: 退出打印完整对话

- **WHEN** 用户退出 TUI
- **THEN** 完整对话(用户消息、agent 回复、工具调用)被打印,无高度截断

### Requirement: 事件驱动与离线可测

TUI SHALL 通过订阅会话事件驱动更新,不轮询;聊天区渲染 SHALL 是纯函数(给定事件序列 → 渲染行),不依赖真实终端即可离线测试。

#### Scenario: 事件驱动更新

- **WHEN** 会话产生事件
- **THEN** TUI 状态随之更新,不进行定时轮询

#### Scenario: 组件渲染离线可测

- **WHEN** 测试注入脚本化事件序列
- **THEN** 可离线断言聊天区渲染结果,无需真实终端

### Requirement: 流式渲染性能

流式渲染 SHALL 达到每秒 ≥30 帧,渲染不阻塞输入、不闪烁。

#### Scenario: 帧率达标

- **WHEN** 持续流式输出
- **THEN** 渲染帧率 ≥30fps,输入响应不被渲染阻塞
