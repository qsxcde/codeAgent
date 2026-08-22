## ADDED Requirements

### Requirement: /sessions 会话恢复命令

TUI `/sessions` 命令 SHALL 支持会话恢复:无参提交 SHALL 弹出交互式选择器(候选含标题,↑↓ 浏览、Enter 切换);`/sessions recent` SHALL 快速恢复最近有活动的会话(无会话时新建);`list` / `new` / `<id>` 既有语义保持;无会话时选择器显示空态,不切换。

#### Scenario: 无参交互式选择恢复

- **WHEN** 用户提交 `/sessions`(无参数)且存在历史会话
- **THEN** 弹出交互式选择器,列出历史会话候选(标题 / id),用户 ↑↓ 选择后 Enter 切换并反馈

#### Scenario: recent 快速恢复

- **WHEN** 用户提交 `/sessions recent`
- **THEN** 恢复最近有活动的会话(无会话时新建),反馈会话 id

#### Scenario: 无会话空态

- **WHEN** 用户提交 `/sessions`(无参数)且无历史会话
- **THEN** 显示空态提示,不切换会话
