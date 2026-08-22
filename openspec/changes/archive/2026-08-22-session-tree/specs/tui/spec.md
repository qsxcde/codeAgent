## ADDED Requirements

### Requirement: /tree 命令

TUI SHALL 提供 `/tree` 斜杠命令:无参 SHALL 展示当前会话所在 fork 链的树形视图(缩进 + 分支字符,节点含标题与 id);`/tree <session-id>` SHALL 切换到指定会话(订阅跟随既有);会话不存在 SHALL 就地提示错误;无会话 SHALL 显示空态。

#### Scenario: 无参展示树

- **WHEN** 用户提交 `/tree` 且存在会话
- **THEN** 展示当前会话所在 fork 链树(缩进与分支字符,节点含标题与 id)

#### Scenario: 切换节点

- **WHEN** 用户提交 `/tree <session-id>` 且会话存在
- **THEN** 切换会话(订阅跟随),反馈结果

#### Scenario: 会话不存在

- **WHEN** 用户提交 `/tree <session-id>` 且会话不存在
- **THEN** 就地提示错误,不切换

### Requirement: /sessions 父子缩进展示

TUI `/sessions list` SHALL 以树形缩进展示会话列表:父会话在其行,子分支会话缩进于其下(复用会话树视图);展示 SHALL 保留标题与 id。

#### Scenario: 列表树形缩进

- **WHEN** 用户提交 `/sessions list` 且会话存在父子关系
- **THEN** 子会话以缩进行展示于其父会话之下,含标题与 id

#### Scenario: 孤儿平级

- **WHEN** 会话列表含父不存在的孤儿会话
- **THEN** 孤儿作为独立根以未缩进展示
