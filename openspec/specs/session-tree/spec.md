# session-tree Specification

## Purpose

定义会话树视图与导航能力:把 fork 产生的会话分支组织为树(纯函数可测),经 TUI `/tree` 命令展示 fork 链并切换节点,`/sessions list` 呈现父子关系——让用户看清分支结构并导航。

## Requirements

### Requirement: 会话树数据视图

系统 SHALL 能把会话列表组织为树:以父会话(`parentSession`)为边,子会话作为父的分支;孤儿会话(父会话不存在)SHALL 作为独立根;同级分支 SHALL 按会话时间排序;纯函数实现,零 I/O,可离线测试。

#### Scenario: 组织 fork 链为树

- **WHEN** 输入包含父会话 A、由 A fork 出的子会话 B 与 C 的会话列表
- **THEN** 树结构中 A 为根,B 与 C 为 A 的子分支(按时间序)

#### Scenario: 孤儿会话作为独立根

- **WHEN** 会话的父会话 id 在列表中不存在
- **THEN** 该会话作为独立根出现在树中,不丢失

#### Scenario: 深层链与多根

- **WHEN** 会话列表含 A→B→C 链且另有独立根 D
- **THEN** 树结构含两个根(A 链与 D),C 为 B 的子分支(深度不受限)

### Requirement: /tree 命令

TUI SHALL 提供 `/tree` 命令:无参 SHALL 展示当前会话 fork 链树(缩进 + 分支字符,节点含标题与 id);`/tree <session-id>` SHALL 切换到指定会话(复用既有切换语义,订阅跟随);会话不存在 SHALL 提示错误;无会话 SHALL 显示空态。

#### Scenario: 无参展示当前树

- **WHEN** 用户提交 `/tree`(无参数)且存在会话
- **THEN** 输出当前会话所在 fork 链的树形展示(缩进与分支字符,节点含标题与 id)

#### Scenario: 切换节点

- **WHEN** 用户提交 `/tree <session-id>` 且该会话存在
- **THEN** 切换到该会话(订阅跟随既有),反馈切换结果

#### Scenario: 会话不存在

- **WHEN** 用户提交 `/tree <session-id>` 且该会话不存在
- **THEN** 提示错误,不切换

#### Scenario: 无会话空态

- **WHEN** 用户提交 `/tree` 且无任何会话
- **THEN** 显示空态提示
