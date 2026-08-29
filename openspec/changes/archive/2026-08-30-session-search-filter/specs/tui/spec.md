## ADDED Requirements

### Requirement: /sessions 搜索和筛选命令

TUI SHALL 提供 `/sessions search <text>` 和 `/sessions filter key=value...` 命令。搜索 SHALL 按标题或会话 id 的不区分大小写文本匹配；筛选 SHALL 支持 `title`、`model`、`status`、`after` 和 `before` 字段。结果 SHALL 展示数量、标题、模型、最近活动时间、状态和会话 id，并复用既有会话 id 切换入口；空结果和无效字段/值 SHALL 就地反馈，不得发起模型请求或改变会话。

#### Scenario: 搜索会话

- **WHEN** 用户提交 `/sessions search auth`
- **THEN** TUI 展示标题或 id 含有 `auth` 的会话结果及匹配数量

#### Scenario: 组合筛选

- **WHEN** 用户提交 `/sessions filter title=auth model=deepseek status=completed`
- **THEN** TUI 只展示同时满足条件的会话，并显示每行的标题、模型、活动时间、状态和 id

#### Scenario: 时间筛选

- **WHEN** 用户提交 `/sessions filter after=2026-08-01 before=2026-08-31`
- **THEN** TUI 按会话最近活动时间筛选并保持既有排序

#### Scenario: 查询错误和空态

- **WHEN** 用户提交空搜索、未知筛选字段、非法状态/时间或没有匹配结果的查询
- **THEN** TUI 显示用法或明确空态，不发起模型请求、不切换当前会话且不写入会话文件

#### Scenario: 既有会话入口兼容

- **WHEN** 用户使用无参 `/sessions`、`/sessions list`、`/sessions recent` 或 `/sessions <id>`
- **THEN** 原有选择器、树形列表、最近恢复和 id 切换行为保持不变
