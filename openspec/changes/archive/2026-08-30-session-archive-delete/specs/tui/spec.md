## MODIFIED Requirements

### Requirement: /sessions 搜索和筛选命令

TUI SHALL 提供 `/sessions search <text>` 和 `/sessions filter key=value...` 命令。搜索 SHALL 按标题或会话 id 的不区分大小写文本匹配；筛选 SHALL 支持 `title`、`model`、`status`、`after` 和 `before` 字段，并默认隐藏已归档会话。结果 SHALL 展示数量、标题、模型、最近活动时间、状态和会话 id，并复用既有会话 id 切换入口；空结果和无效字段/值 SHALL 就地反馈，不得发起模型请求或改变会话。

#### Scenario: 搜索会话

- **WHEN** 用户提交 `/sessions search auth`
- **THEN** TUI 展示标题或 id 含有 `auth` 的未归档会话结果及匹配数量

#### Scenario: 组合筛选

- **WHEN** 用户提交 `/sessions filter title=auth model=deepseek status=completed`
- **THEN** TUI 只展示同时满足条件的未归档会话，并显示每行的标题、模型、活动时间、状态和 id

#### Scenario: 时间筛选

- **WHEN** 用户提交 `/sessions filter after=2026-08-01 before=2026-08-31`
- **THEN** TUI 按会话最近活动时间筛选并保持既有排序

#### Scenario: 查询错误和空态

- **WHEN** 用户提交空搜索、未知筛选字段、非法状态/时间或没有匹配结果的查询
- **THEN** TUI 显示用法或明确空态，不发起模型请求、不切换当前会话且不写入会话文件

#### Scenario: 既有会话入口兼容

- **WHEN** 用户使用无参 `/sessions`、`/sessions list`、`/sessions recent` 或 `/sessions <id>`
- **THEN** 原有选择器、树形列表、最近恢复和 id 切换行为保持不变，已归档会话遵循默认隐藏规则

### Requirement: /sessions 会话整理命令

TUI SHALL 提供 `/sessions archive <id...>`、`/sessions unarchive <id...>`、`/sessions archived` 和 `/sessions delete <id...> confirm`。归档与恢复 SHALL 只更新目标会话状态；删除和批量删除 SHALL 只有在命令末尾提供显式 `confirm` 时执行，并对当前/运行中会话、非法目标、失败和部分结果就地反馈。所有整理命令 SHALL 不发起模型请求，且不得误切换当前会话。

#### Scenario: 归档和查看

- **WHEN** 用户提交 `/sessions archive <id>` 后提交 `/sessions archived`
- **THEN** 会话从默认列表隐藏并出现在归档列表，反馈包含目标 id 和归档状态

#### Scenario: 取消归档

- **WHEN** 用户提交 `/sessions unarchive <id>`
- **THEN** 会话恢复到默认搜索/筛选和列表中，历史消息与当前会话不变

#### Scenario: 删除确认

- **WHEN** 用户提交 `/sessions delete <id>` 或批量 id 但未附带 `confirm`
- **THEN** TUI 拒绝执行并显示确认用法，目标文件、索引和会话状态保持不变

#### Scenario: 删除执行与保护

- **WHEN** 用户提交 `/sessions delete <id...> confirm`
- **THEN** 合法的非当前、非运行目标被删除并反馈结果；受保护或失败目标保留并显示原因，不触发模型或工具运行

#### Scenario: 整理空态和错误

- **WHEN** 目标不存在、归档列表为空或命令参数非法
- **THEN** TUI 就地显示明确错误/空态，不创建会话、不切换会话、不提交普通对话文本
