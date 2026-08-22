## ADDED Requirements

### Requirement: 会话树视图

会话列表 SHALL 可组织为 fork 树视图:子会话 SHALL 挂在父会话(`parentSession`)之下;父会话不存在的孤儿 SHALL 作为独立根;同级按会话时间排序;该视图 SHALL 纯函数可测(零 I/O),供 TUI `/tree` 与 `/sessions` 列表共用。

#### Scenario: 父子挂接

- **WHEN** 会话列表含父会话 A 与子会话 B(fork 自 A)
- **THEN** B 挂在 A 之下作为分支

#### Scenario: 孤儿独立根

- **WHEN** 会话的父会话 id 不存在于列表
- **THEN** 该会话作为独立根展示,不丢失

#### Scenario: 同级按时间排序

- **WHEN** 同一父会话下存在多个分支子会话
- **THEN** 分支按会话时间排序展示
