# sessions Specification

## Purpose

定义会话持久化能力:会话以 JSONL 树形文件落盘(append-only、显式父子关系),进程重启后会话可列出、可恢复继续对话,格式带版本策略以支持演进。

## Requirements

### Requirement: JSONL 树形会话文件

每个会话 SHALL 对应一个 JSONL 文件,写入 SHALL 为追加式(append-only,不重写历史);文件 SHALL 以会话头 entry 开始;后续 entry 类型 SHALL 包括消息(带全局唯一 id 与父级 id)与压缩记录;消息之间的因果结构 SHALL 由父级 id 显式表达,而非仅靠物理顺序。

#### Scenario: 追加写入

- **WHEN** 会话产生新消息
- **THEN** 新消息作为新 entry 追加到文件末尾,历史 entry 不被修改

#### Scenario: 消息父级关系

- **WHEN** 消息写入会话文件
- **THEN** 每条消息带有父级 id,指向其直接前驱,回放与回滚可沿父级链定位

#### Scenario: 压缩记录

- **WHEN** 会话被压缩
- **THEN** 压缩摘要作为压缩 entry 追加到文件(含摘要文本与涉及的文件操作记录),旧消息仍保留在文件中

### Requirement: 会话恢复

进程重启后 SHALL 能列出全部会话及其元数据;SHALL 能从会话文件恢复消息历史并继续对话(继续对话时新消息追加到同一会话文件)。

#### Scenario: 重启后列出会话

- **WHEN** 新进程启动并请求会话列表
- **THEN** 返回既有会话及其元数据(标识、标题、时间等)

#### Scenario: 恢复并继续

- **WHEN** 用户选择既有会话继续对话
- **THEN** 该会话历史消息恢复,后续对话消息追加到同一文件,上下文连续

### Requirement: 分叉基础与格式版本

会话文件格式 SHALL 为未来分叉预留:会话头 SHALL 可记录父会话标识;文件 SHALL 带格式版本号,读侧 SHALL 按版本解析(未来格式演进可迁移)。

#### Scenario: 父会话标识

- **WHEN** 会话由既有会话分叉产生
- **THEN** 其会话头记录父会话标识,消息父级链从分叉点延续

#### Scenario: 版本化解析

- **WHEN** 读取会话文件
- **THEN** 解析器按文件声明的格式版本处理;版本不兼容时给出明确错误而非静默误读
