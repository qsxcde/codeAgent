## Purpose

TUI 会话快速恢复与交互式选择恢复能力:增强 `/sessions` 命令,使"恢复最近会话"(`recent` 快捷)与"从历史会话中选择切换"(无参交互式选择器)可经 TUI 直达,复用既有补全浮层与订阅跟随,无需新增独立命令。

## ADDED Requirements

### Requirement: /sessions 交互式选择恢复

TUI `/sessions` 命令无参提交时 SHALL 弹出交互式选择器,列出历史会话候选(标题 / id / 时间),支持 ↑↓ 浏览与 Enter 确认切换;候选 SHALL 来自会话列表(含派生标题);确认后 SHALL 切换会话并反馈结果(订阅跟随既有语义);无会话时 SHALL 显示空态提示,不产生切换。

#### Scenario: 无参弹选择器并切换

- **WHEN** 用户提交 `/sessions`(无参数)且存在历史会话
- **THEN** 弹出交互式选择器,候选按会话列表展示(含标题);用户 ↑↓ 选择、Enter 确认后切换到所选会话并反馈

#### Scenario: 无会话空态

- **WHEN** 用户提交 `/sessions`(无参数)且无任何历史会话
- **THEN** 选择器显示空态提示,不切换会话

### Requirement: /sessions recent 快速恢复

TUI `/sessions recent` SHALL 恢复最近有活动的会话(`continue_recent` 语义);没有任何会话时 SHALL 新建会话并反馈。恢复后 SHALL 成为当前会话,订阅跟随既有语义。

#### Scenario: 有会话时恢复最近

- **WHEN** 用户提交 `/sessions recent` 且存在历史会话
- **THEN** 切换到最近有活动的会话并反馈其 id

#### Scenario: 无会话时新建

- **WHEN** 用户提交 `/sessions recent` 且无任何历史会话
- **THEN** 新建会话并反馈新会话 id

### Requirement: /sessions 既有语义保持

`/sessions list`、`/sessions new`、`/sessions <id>` SHALL 保持既有行为:列出全部会话、新建会话、按 id 切换会话(不存在时报错提示);`recent` 与无参选择器为新增分支,不改变既有命令的向后兼容语义。

#### Scenario: 既有语义回归

- **WHEN** 用户提交 `/sessions list` / `/sessions new` / `/sessions <id>`
- **THEN** 行为与既有版本一致(列表 / 新建 / 切换或错误提示)
