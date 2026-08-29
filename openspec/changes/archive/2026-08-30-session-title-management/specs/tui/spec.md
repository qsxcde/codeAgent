## ADDED Requirements

### Requirement: /name 会话标题命令

TUI SHALL 提供 `/name` 会话标题命令。`/name <title>` SHALL 为当前会话设置标题并反馈实际生效的归一化标题;不带标题时 SHALL 显示当前标题和用法。没有当前会话、当前环境没有持久化后端或标题无效时 SHALL 显示明确错误,不得误发起模型请求或改变聊天历史。

#### Scenario: 设置会话标题

- **WHEN** 用户提交 `/name 重构 auth 模块`
- **THEN** 当前会话标题被持久化,聊天区反馈标题已更新,后续 `/sessions` 和 `/tree` 展示新标题

#### Scenario: 显示当前标题和用法

- **WHEN** 用户提交 `/name` 且存在当前会话
- **THEN** TUI 显示当前标题和 `/name <title>` 用法,不修改会话

#### Scenario: 命名错误不改变会话

- **WHEN** 用户在无当前会话、无持久化后端或输入空白标题时提交 `/name`
- **THEN** TUI 显示可操作错误,不发起对话、不改写历史消息且保留原标题
