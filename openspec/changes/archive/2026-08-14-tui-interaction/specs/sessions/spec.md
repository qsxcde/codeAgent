## ADDED Requirements

### Requirement: 运行时可切换模型配置

会话管理器 SHALL 支持运行时切换 provider / model / effort:切换后当前会话后续轮次 SHALL 使用新配置,既有消息历史 SHALL 不被改写;配置切换 SHALL 以模型变更记录追加到会话文件(append-only),读侧取最近一次配置,进程重启后会话元数据 SHALL 反映最新配置。

#### Scenario: 热切换

- **WHEN** 用户切换 provider / model / effort
- **THEN** 当前会话后续对话轮次使用新配置,既有消息历史不被改写

#### Scenario: 变更持久化

- **WHEN** 会话发生模型配置切换
- **THEN** 变更作为模型变更 entry 追加到会话文件末尾,读侧取最近一次配置

#### Scenario: 切换后继续

- **WHEN** 配置切换后用户继续对话
- **THEN** 会话上下文连续,新消息写入同一会话文件,重启后按最新配置恢复
